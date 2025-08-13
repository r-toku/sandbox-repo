#!/usr/bin/env python3
"""オープン中のプルリクエスト情報を取得し Markdown に整形して出力するスクリプト

GitHub CLI (`gh`) を利用して以下の情報を収集する。

* オープン中 PR の基本情報
* レビューの状況や割り当てられたレビュワー
* Projects (v2) に紐付くフィールド値

`--repo` 引数で対象リポジトリを指定可能で、リポジトリごとの Markdown を出力する。
収集した内容を Wiki に掲載するための Markdown 形式にまとめる。
"""
import argparse
import datetime
import json
import os
import subprocess
import logging
import base64
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
        logger.error(f"gh command failed: {err_msg}")
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

def main(output_dir: str, repo: str = "") -> None:
    os.makedirs(output_dir, exist_ok=True)
    # 取得対象のリポジトリを決定し、gh コマンド用の引数と出力ファイル名を組み立てる
    if repo:
        repo_arg = ["--repo", repo]
        file_suffix = repo.replace("/", "_")
    else:
        repo_env = os.environ.get("GITHUB_REPOSITORY", "")
        repo = repo_env
        repo_arg = ["--repo", repo] if repo else []
        file_suffix = repo.replace("/", "_") if repo else "unknown"
    output_file = os.path.join(output_dir, f"PR_Status_{file_suffix}.md")

    # 環境変数 LOGIN_USERS_B64 をデコードしてユーザーと組織の対応表を作成
    login_user_map: Dict[str, str] = {}
    org_order: List[str] = []
    encoded = os.environ.get("LOGIN_USERS_B64")
    if encoded:
        try:
            decoded = base64.b64decode(encoded).decode()
            login_users_json = json.loads(decoded)
            logger.debug(
                f"LOGIN_USERS_JSON={json.dumps(login_users_json, ensure_ascii=False)}"
            )  # デコード結果を出力
            for item in login_users_json.get("loginUsers", []):
                login = item.get("loginUser")
                org = item.get("organization")
                if login and org:
                    login_user_map[login] = org
                    if org not in org_order:
                        org_order.append(org)
        except Exception as e:
            # デコードや JSON パースに失敗した場合はログに記録して空のマッピングを利用する
            logger.error(f"LOGIN_USERS_B64 decode failed: {e}")
    else:
        logger.warning("LOGIN_USERS_B64 is not set")

    # Markdown のヘッダを動的に生成する
    reviewer_cols = [f"{org} Reviewers" for org in org_order + ["other"]]
    header_cols = [
        "PR",
        "Title",
        "状態",
        *reviewer_cols,
        "Assignees",
        "Status",
        "Priority",
        "Target Date",
        "Sprint",
    ]
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# Pull Request Status for {repo}\n\n")
        f.write(f"Updated: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
        f.write("| " + " | ".join(header_cols) + " |\n")
        f.write("| " + " | ".join(["---"] * len(header_cols)) + " |\n")

    # 1. オープン中の PR 一覧を取得
    #    number や title などの基本情報をまとめて JSON 形式で取得する
    pr_list_cmd = [
        "gh", "pr", "list", "--state", "open", "--limit", "100",
        "--json", "number,title,author,createdAt,updatedAt,url,isDraft",
    ] + repo_arg
    pr_list_json = run_gh(pr_list_cmd)
    logger.debug(f"PR_LIST={pr_list_json}")
    pr_list = json.loads(pr_list_json)

    for pr in pr_list:
        # 2. PR 詳細を取得
        #    レビュー履歴(reviews)、レビュー依頼(reviewRequests)、アサイン(assignees)を取得する
        number = pr["number"]
        title = pr["title"].replace("\n", " ").replace("|", "\\|")
        url = pr["url"]
        is_draft = pr.get("isDraft", False)

        details_cmd = [
            "gh", "pr", "view", str(number), "--json", "reviews,reviewRequests,assignees",
        ] + repo_arg
        details_json = run_gh(details_cmd)
        logger.debug(f"DETAILS for PR {number}={details_json}")
        details = json.loads(details_json)
        reviews = details.get("reviews", [])
        requested = [r["login"] for r in details.get("reviewRequests", [])]
        assignees = [a["login"] for a in details.get("assignees", [])]
        assignees_str = " ".join(assignees) if assignees else "未割当"

        # レビュワーごとの最新ステータスを保持する辞書
        reviewer_states = {r: "PENDING" for r in requested}
        # submittedAt で昇順に並べ替えて最新レビューを反映する
        sorted_reviews = sorted(
            reviews, key=lambda x: x.get("submittedAt", "")
        )
        for r in sorted_reviews:
            author = r.get("author")
            if not author:
                continue
            login = author.get("login")
            if not login:
                continue
            # 現在レビュー再依頼中のレビュワーは保留状態のままにする
            if login in requested:
                continue
            # 同一レビュワーが複数回レビューした場合は最後の状態を採用する
            reviewer_states[login] = r.get("state", "")
        # 組織ごとにレビュワーを分類し各列に表示する文字列を生成する
        org_groups: Dict[str, List[str]] = {org: [] for org in org_order}
        org_groups["other"] = []
        for reviewer, state in reviewer_states.items():
            org = login_user_map.get(reviewer, "other")
            org_groups.setdefault(org, []).append(
                format_reviewer_status(reviewer, state)
            )

        pr_status = determine_pr_status(reviews, is_draft)

        # 3. Projects (v2) のフィールド値を GraphQL で取得
        #    まず gh pr view で PR の node ID を取得する
        node_cmd = ["gh", "pr", "view", str(number), "--json", "id", "-q", ".id"] + repo_arg
        pr_node_id = run_gh(node_cmd).strip()
        logger.debug(f"PR_NODE_ID for PR {number}={pr_node_id}")

        # プロジェクトアイテムに紐付く任意フィールドを取得するクエリ
        # PullRequest の projectItems から fieldValues を列挙し、
        # 各フィールド型ごとに name/text/date などの値を取り出す
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
        # 上記クエリを gh api graphql で実行してフィールド値を取得する
        try:
            project_json_str = run_gh([
                "gh", "api", "graphql",
                "-f", f"query={graphql_query}", "-f", f"PR_NODE_ID={pr_node_id}",
            ])
            logger.debug(f"PROJECT_JSON for PR {number}={project_json_str}")
            project_json = json.loads(project_json_str)
            field_names = [
                "Status",
                "Priority",
                "Target Date",
                "Sprint",
            ]
            field_values = extract_fields(project_json, field_names)
            status = field_values["Status"]
            priority = field_values["Priority"]
            target_date = field_values["Target Date"]
            sprint = field_values["Sprint"]
        except subprocess.CalledProcessError as e:
            # gh コマンドが失敗した場合はエラーメッセージを出力し、値を "-" とする
            logger.error(f"PROJECT_JSON fetch failed for PR {number}: {e.stderr}")
            status = priority = target_date = sprint = "-"
        except json.JSONDecodeError as e:
            # JSON パースに失敗した場合も値を "-" とする
            logger.error(f"PROJECT_JSON parse failed for PR {number}: {e}")
            status = priority = target_date = sprint = "-"

        # Markdown 出力用の行を組み立てる
        row_fields: List[str] = [
            f"#{number}",
            f"[{title}]({url})",
            pr_status,
        ]
        for org in org_order + ["other"]:
            names = org_groups.get(org)
            row_fields.append(" ".join(names) if names else "-")
        row_fields.extend(
            [assignees_str, status, priority, target_date, sprint]
        )
        row = "| " + " | ".join(row_fields) + " |\n"
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(row)

    logger.info(f"PR 情報を {output_file} に出力しました")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PR 情報を収集して Markdown に出力します")
    parser.add_argument("output_dir", nargs="?", default=".")
    parser.add_argument("--repo", help="対象とするリポジトリ (owner/name)", default="")
    args = parser.parse_args()
    main(args.output_dir, args.repo)
