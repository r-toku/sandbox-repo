#!/usr/bin/env python3
"""オープン中のプルリクエスト情報を取得し Markdown に整形して出力するスクリプト

GitHub CLI (`gh`) を利用して以下の情報を収集する。

* オープン中 PR の基本情報
* レビューの状況や割り当てられたレビュワー
* Projects (v2) に紐付くフィールド値

収集した内容を Wiki に掲載するための Markdown 形式にまとめる。
"""
import argparse
import datetime
import json
import os
import subprocess
from typing import List, Dict, Any

def determine_pr_status(reviews: List[Dict[str, Any]], is_draft: bool) -> str:
    """レビュー結果から PR のステータス文字列を判定する

    ドラフトであれば常に「ドラフト」とし、レビューの状態に応じて
    「承認済み」「修正依頼」「レビュー中」「未レビュー」を返す。
    """
    if is_draft:
        return "ドラフト"
    approved = [r for r in reviews if r.get("state") == "APPROVED"]
    changes = [r for r in reviews if r.get("state") == "CHANGES_REQUESTED"]
    if approved:
        return "承認済み"
    if changes:
        return "修正依頼"
    if reviews:
        return "レビュー中"
    return "未レビュー"

def format_reviewer_status(reviewer: str, state: str) -> str:
    """レビュー状態に応じてレビュワー名に絵文字を付加する"""
    mapping = {
        "APPROVED": "✅",
        "CHANGES_REQUESTED": "❌",
        "COMMENTED": "💬",
        "PENDING": "⏳",
        "": "⏳",
    }
    return f"{reviewer}{mapping.get(state, '')}"

def run_gh(args: List[str]) -> str:
    """gh コマンドを実行し結果を文字列で返す

    失敗時は標準出力・標準エラーの内容を表示して `CalledProcessError` を送出する。
    """
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        # エラー出力があれば優先して表示し、なければ標準出力を表示する
        err_msg = (result.stderr or result.stdout).strip()
        print(f"gh command failed: {err_msg}")
        raise subprocess.CalledProcessError(
            result.returncode, args, output=result.stdout, stderr=result.stderr
        )
    return result.stdout

def extract_fields(project_json: Dict[str, Any], fields: List[str]) -> Dict[str, str]:
    """Projects のフィールド値から指定した項目だけを抜き出す

    `fieldValues.nodes` に現れる複数の値から、必要なフィールド名のみを
    探索して返却する。存在しないフィールドは "-" で埋める。
    """
    result = {f: "-" for f in fields}
    nodes = (
        project_json
        .get("data", {})
        .get("node", {})
        .get("projectItems", {})
        .get("nodes", [])
    )
    for n in nodes:
        fv_nodes = n.get("fieldValues", {}).get("nodes", [])
        for fv in fv_nodes:
            name = fv.get("field", {}).get("name")
            if name not in result:
                continue
            number_value = fv.get("number")
            value = (
                fv.get("text")
                or fv.get("date")
                or fv.get("name")
                or fv.get("title")
                or (str(number_value) if number_value is not None else None)
            )
            if value:
                # 進捗フィールドは数値を百分率に変換して扱う
                if name == "Sub-issues progress" and number_value is not None:
                    result[name] = f"{int(number_value)}%"
                else:
                    result[name] = value
            elif isinstance(fv.get("milestone"), dict):
                # マイルストーン値はタイトルを取り出す
                m_title = fv["milestone"].get("title")
                if m_title:
                    result[name] = m_title
    return result

def main(output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "PR_Status.md")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# Pull Request Status\n\n")
        f.write(f"Updated: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
        f.write(
            "| PR | Title | 状態 | Reviewers | Assignees | Status | Sub-issues progress | Priority | Size | Estimate | Start date | End date | Sprint |\n"
        )
        f.write(
            "| --- | ----- | ---- | --------- | --------- | ------ | ------------------- | -------- | ---- | -------- | ---------- | --------- | ------ |\n"
        )

    # 1. オープン中の PR 一覧を取得
    pr_list_json = run_gh([
        "gh", "pr", "list", "--state", "open", "--limit", "100",
        "--json", "number,title,author,createdAt,updatedAt,url,isDraft",
    ])
    print(f"PR_LIST={pr_list_json}")
    pr_list = json.loads(pr_list_json)

    for pr in pr_list:
        # 2. PR 詳細を取得
        number = pr["number"]
        title = pr["title"].replace("\n", " ").replace("|", "\\|")
        url = pr["url"]
        is_draft = pr.get("isDraft", False)

        details_json = run_gh(["gh", "pr", "view", str(number), "--json", "reviews,reviewRequests,assignees"])
        print(f"DETAILS for PR {number}={details_json}")
        details = json.loads(details_json)
        reviews = details.get("reviews", [])
        requested = [r["login"] for r in details.get("reviewRequests", [])]
        assignees = [a["login"] for a in details.get("assignees", [])]
        assignees_str = " ".join(assignees) if assignees else "未割当"

        # レビュワーのステータス文字列を生成
        reviewer_info_list = [format_reviewer_status(r, "PENDING") for r in requested]
        unique_reviews = {}
        for r in reviews:
            unique_reviews[r["user"]["login"]] = r["state"]
        for reviewer, state in unique_reviews.items():
            reviewer_info_list.append(format_reviewer_status(reviewer, state))
        reviewer_info = "<br>".join(reviewer_info_list) if reviewer_info_list else "未割当"

        pr_status = determine_pr_status(reviews, is_draft)

        # 3. Projects (v2) のフィールド値を GraphQL で取得
        pr_node_id = run_gh(["gh", "pr", "view", str(number), "--json", "id", "-q", ".id"]).strip()
        print(f"PR_NODE_ID for PR {number}={pr_node_id}")

        # プロジェクトアイテムに紐付く任意フィールドを取得するクエリ
        graphql_query = (
            "query($PR_NODE_ID: ID!) {\n"
            "  node(id: $PR_NODE_ID) {\n"
            "    ... on PullRequest {\n"
            "      projectItems(first: 1) {\n"
            "        nodes {\n"
            "          fieldValues(first: 20) {\n"
            "            nodes {\n"
            "              __typename\n"
            "              ... on ProjectV2ItemFieldSingleSelectValue {\n"
            "                field { ... on ProjectV2FieldCommon { name } }\n"
            "                name\n"
            "              }\n"
            "              ... on ProjectV2ItemFieldTextValue {\n"
            "                field { ... on ProjectV2FieldCommon { name } }\n"
            "                text\n"
            "              }\n"
            "              ... on ProjectV2ItemFieldDateValue {\n"
            "                field { ... on ProjectV2FieldCommon { name } }\n"
            "                date\n"
            "              }\n"
            "              ... on ProjectV2ItemFieldIterationValue {\n"
            "                field { ... on ProjectV2FieldCommon { name } }\n"
            "                title\n"
            "              }\n"
            "              ... on ProjectV2ItemFieldNumberValue {\n"
            "                field { ... on ProjectV2FieldCommon { name } }\n"
            "                number\n"
            "              }\n"
            "              ... on ProjectV2ItemFieldMilestoneValue {\n"
            "                field { ... on ProjectV2FieldCommon { name } }\n"
            "                milestone { title }\n"
            "              }\n"
            "            }\n"
            "          }\n"
            "        }\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        try:
            project_json_str = run_gh([
                "gh", "api", "graphql",
                "-f", f"query={graphql_query}", "-f", f"PR_NODE_ID={pr_node_id}",
            ])
            print(f"PROJECT_JSON for PR {number}={project_json_str}")
            project_json = json.loads(project_json_str)
            field_names = [
                "Status",
                "Sub-issues progress",
                "Priority",
                "Size",
                "Estimate",
                "Start date",
                "End date",
                "Sprint",
            ]
            field_values = extract_fields(project_json, field_names)
            status = field_values["Status"]
            sub_issues = field_values["Sub-issues progress"]
            priority = field_values["Priority"]
            size = field_values["Size"]
            estimate = field_values["Estimate"]
            start_date = field_values["Start date"]
            end_date = field_values["End date"]
            sprint = field_values["Sprint"]
        except subprocess.CalledProcessError as e:
            # gh コマンドが失敗した場合はエラーメッセージを出力し、値を "-" とする
            print(f"PROJECT_JSON fetch failed for PR {number}: {e.stderr}")
            status = sub_issues = priority = size = estimate = start_date = end_date = sprint = "-"
        except json.JSONDecodeError as e:
            # JSON パースに失敗した場合も値を "-" とする
            print(f"PROJECT_JSON parse failed for PR {number}: {e}")
            status = sub_issues = priority = size = estimate = start_date = end_date = sprint = "-"

        row = (
            f"| #{number} | [{title}]({url}) | {pr_status} | {reviewer_info} | {assignees_str} | "
            f"{status} | {sub_issues} | {priority} | {size} | {estimate} | {start_date} | {end_date} | {sprint} |\n"
        )
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(row)

    print(f"PR 情報を {output_file} に出力しました")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PR 情報を収集して Markdown に出力します")
    parser.add_argument("output_dir", nargs="?", default=".")
    args = parser.parse_args()
    main(args.output_dir)
