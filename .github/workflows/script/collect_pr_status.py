#!/usr/bin/env python3
"""オープン中のプルリクエスト情報を取得しMarkdownに出力するスクリプト"""
import argparse
import datetime
import json
import os
import subprocess
from typing import List, Dict, Any

# PR のステータスを判定する
# 引数:
#   reviews   - レビュー情報のリスト
#   is_draft  - ドラフトかどうか
def determine_pr_status(reviews: List[Dict[str, Any]], is_draft: bool) -> str:
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

# レビュワーの状態を絵文字付きで整形する
# 引数:
#   reviewer - レビュワー名
#   state    - レビュー状態
def format_reviewer_status(reviewer: str, state: str) -> str:
    mapping = {
        "APPROVED": "✅",
        "CHANGES_REQUESTED": "❌",
        "COMMENTED": "💬",
        "PENDING": "⏳",
        "": "⏳",
    }
    return f"{reviewer}{mapping.get(state, '')}"

# gh コマンドを実行するユーティリティ
def run_gh(args: List[str]) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout

# プロジェクト情報からフィールドを抽出する
def extract_field(project_json: Dict[str, Any], field: str) -> str:
    nodes = project_json.get("data", {}).get("node", {}).get("projectItems", {}).get("nodes", [])
    for n in nodes:
        value = n.get(field)
        if isinstance(value, dict):
            for key in ("date", "name", "text"):
                v = value.get(key)
                if v:
                    return v
        elif value:
            return value
    return "-"

def main(output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "PR_Status.md")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# Pull Request Status\n\n")
        f.write(f"Updated: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
        f.write("| PR | Title | 状態 | Reviewers | Assignees | Status | Priority | Sprint | End date |\n")
        f.write("| --- | ----- | ---- | --------- | --------- | ------ | -------- | ------ | --------- |\n")

    pr_list_json = run_gh([
        "gh", "pr", "list", "--state", "open", "--limit", "100",
        "--json", "number,title,author,createdAt,updatedAt,url,isDraft",
    ])
    print(f"PR_LIST={pr_list_json}")
    pr_list = json.loads(pr_list_json)

    for pr in pr_list:
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

        reviewer_info_list = [format_reviewer_status(r, "PENDING") for r in requested]
        unique_reviews = {}
        for r in reviews:
            unique_reviews[r["user"]["login"]] = r["state"]
        for reviewer, state in unique_reviews.items():
            reviewer_info_list.append(format_reviewer_status(reviewer, state))
        reviewer_info = "<br>".join(reviewer_info_list) if reviewer_info_list else "未割当"

        pr_status = determine_pr_status(reviews, is_draft)

        pr_node_id = run_gh(["gh", "pr", "view", str(number), "--json", "id", "-q", ".id"]).strip()
        print(f"PR_NODE_ID for PR {number}={pr_node_id}")

        graphql_query = (
            "query($PR_NODE_ID: ID!) {\n"
            "  node(id: $PR_NODE_ID) {\n"
            "    ... on PullRequest {\n"
            "      projectItems(first: 1) {\n"
            "        nodes {\n"
            "          status { name text }\n"
            "          priority { name text }\n"
            "          sprint { name text }\n"
            "          endDate { date text }\n"
            "        }\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        try:
            project_json_str = run_gh([
                "gh", "api", "graphql", "-H", "GraphQL-Features: projects_next_graphql",
                "-f", f"query={graphql_query}", "-f", f"PR_NODE_ID={pr_node_id}",
            ])
            print(f"PROJECT_JSON for PR {number}={project_json_str}")
            project_json = json.loads(project_json_str)
            status = extract_field(project_json, "status")
            priority = extract_field(project_json, "priority")
            sprint = extract_field(project_json, "sprint")
            end_date = extract_field(project_json, "endDate")
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            # プロジェクト情報の取得に失敗した場合は空欄を設定する
            print(f"PROJECT_JSON fetch failed for PR {number}: {e}")
            status = priority = sprint = end_date = "-"

        with open(output_file, "a", encoding="utf-8") as f:
            f.write(
                f"| #{number} | [{title}]({url}) | {pr_status} | {reviewer_info} | {assignees_str} | {status} | {priority} | {sprint} | {end_date} |\n"
            )

    print(f"PR 情報を {output_file} に出力しました")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PR 情報を収集して Markdown に出力します")
    parser.add_argument("output_dir", nargs="?", default=".")
    args = parser.parse_args()
    main(args.output_dir)
