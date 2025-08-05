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
import logging
from typing import List, Dict, Any

# 環境変数 LOG_LEVEL を参照してログレベルを設定
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

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
        logger.error("gh command failed: %s", err_msg)
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
            "| PR | Title | 状態 | Reviewers | Assignees | Status | Priority | Target Date | Sprint |\n"
        )
        f.write(
            "| --- | ----- | ---- | --------- | --------- | ------ | -------- | ----------- | ------ |\n"
        )

    # 1. オープン中の PR 一覧を取得
    pr_list_json = run_gh([
        "gh", "pr", "list", "--state", "open", "--limit", "100",
        "--json", "number,title,author,createdAt,updatedAt,url,isDraft",
    ])
    logger.debug("PR_LIST=%s", pr_list_json)
    pr_list = json.loads(pr_list_json)

    for pr in pr_list:
        # 2. PR 詳細を取得
        number = pr["number"]
        title = pr["title"].replace("\n", " ").replace("|", "\\|")
        url = pr["url"]
        is_draft = pr.get("isDraft", False)

        details_json = run_gh(["gh", "pr", "view", str(number), "--json", "reviews,reviewRequests,assignees"])
        logger.debug("DETAILS for PR %s=%s", number, details_json)
        details = json.loads(details_json)
        reviews = details.get("reviews", [])
        requested = [r["login"] for r in details.get("reviewRequests", [])]
        assignees = [a["login"] for a in details.get("assignees", [])]
        assignees_str = " ".join(assignees) if assignees else "未割当"

        # レビュワーごとの最新ステータスを保持する辞書
        reviewer_states = {r: "PENDING" for r in requested}
        for r in reviews:
            author = r.get("author")
            if not author:
                continue
            login = author.get("login")
            if not login:
                continue
            # レビュー再依頼中であれば過去の結果を無視する
            if login in reviewer_states:
                continue
            # 同一レビュワーが複数回レビューした場合は最後の状態を採用する
            reviewer_states[login] = r.get("state", "")

        reviewer_info_list = [
            format_reviewer_status(reviewer, state)
            for reviewer, state in reviewer_states.items()
        ]
        reviewer_info = "<br>".join(reviewer_info_list) if reviewer_info_list else "未割当"

        pr_status = determine_pr_status(reviews, is_draft)

        # 3. Projects (v2) のフィールド値を GraphQL で取得
        pr_node_id = run_gh(["gh", "pr", "view", str(number), "--json", "id", "-q", ".id"]).strip()
        logger.debug("PR_NODE_ID for PR %s=%s", number, pr_node_id)

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
            logger.debug("PROJECT_JSON for PR %s=%s", number, project_json_str)
            project_json = json.loads(project_json_str)
            field_names = [
                "Status",
                "Priority",
                "Target date",
                "Sprint",
            ]
            field_values = extract_fields(project_json, field_names)
            status = field_values["Status"]
            priority = field_values["Priority"]
            target_date = field_values["Target date"]
            sprint = field_values["Sprint"]
        except subprocess.CalledProcessError as e:
            # gh コマンドが失敗した場合はエラーメッセージを出力し、値を "-" とする
            logger.error("PROJECT_JSON fetch failed for PR %s: %s", number, e.stderr)
            status = priority = target_date = sprint = "-"
        except json.JSONDecodeError as e:
            # JSON パースに失敗した場合も値を "-" とする
            logger.error("PROJECT_JSON parse failed for PR %s: %s", number, e)
            status = priority = target_date = sprint = "-"

        row = (
            f"| #{number} | [{title}]({url}) | {pr_status} | {reviewer_info} | {assignees_str} | "
            f"{status} | {priority} | {target_date} | {sprint} |\n"
        )
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(row)

    logger.info("PR 情報を %s に出力しました", output_file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PR 情報を収集して Markdown に出力します")
    parser.add_argument("output_dir", nargs="?", default=".")
    args = parser.parse_args()
    main(args.output_dir)
