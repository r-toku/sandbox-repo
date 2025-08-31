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
from typing import List, Dict, Any, Set, Optional

# 環境変数 LOG_LEVEL を参照してログレベルを設定
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

def determine_pr_status(
    reviewer_states: Dict[str, str],
    is_draft: bool,
    required_reviewers: Set[str],
) -> str:
    """レビューの状態と必須レビュワーの承認状況から
    PR のステータス文字列を判定する"""

    # ドラフトであれば常にドラフトを返す
    if is_draft:
        return "ドラフト"

    # コメントが一件もない場合は未レビュー
    if not reviewer_states or all(s == "PENDING" for s in reviewer_states.values()):
        return "未レビュー"

    # 修正依頼がある場合は修正依頼を優先
    if any(s == "CHANGES_REQUESTED" for s in reviewer_states.values()):
        return "修正依頼"

    # 承認済みの判定
    approvals = {u for u, s in reviewer_states.items() if s == "APPROVED"}
    required_for_pr = required_reviewers & reviewer_states.keys()
    if required_for_pr and required_for_pr.issubset(approvals):
        return "承認済み"
    if approvals and all(s == "APPROVED" for s in reviewer_states.values()):
        return "承認済み"

    # 上記以外はレビュー中
    return "レビュー中"

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

def run_gh(args: List[str], input_text: Optional[str] = None) -> str:
    """gh コマンドを実行し結果を文字列で返す

    `input_text` が指定された場合は標準入力として渡す。
    失敗時は標準出力・標準エラーの内容を表示して `CalledProcessError` を送出する。
    """
    result = subprocess.run(args, input=input_text, capture_output=True, text=True)
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

# Project フィールド定義のキャッシュ
PROJECT_FIELD_CATALOG_CACHE: Dict[str, Dict[str, Dict[str, Any]]] = {}

def get_first_development_issue_id(pr_node_id: str) -> Optional[str]:
    """Development に紐づく最初の Issue の node ID を取得する"""
    query = (
        "query($PR_ID: ID!) {\n"
        "  node(id: $PR_ID) {\n"
        "    ... on PullRequest {\n"
        "      closingIssuesReferences(first: 20) { nodes { id } }\n"
        "      timelineItems(itemTypes: [CONNECTED_EVENT, CROSS_REFERENCED_EVENT], first: 20) {\n"
        "        nodes {\n"
        "          __typename\n"
        "          ... on ConnectedEvent { subject { ... on Issue { id } } }\n"
        "          ... on CrossReferencedEvent { source { ... on Issue { id } } }\n"
        "        }\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    try:
        res = run_gh([
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-f", f"PR_ID={pr_node_id}",
        ])
        data = json.loads(res).get("data", {}).get("node", {})
        refs = data.get("closingIssuesReferences", {}).get("nodes", [])
        if refs:
            return refs[0].get("id")
        timeline = data.get("timelineItems", {}).get("nodes", [])
        for t in timeline:
            if t.get("__typename") == "ConnectedEvent":
                subj = t.get("subject", {})
                if subj.get("id") and subj.get("__typename") == "Issue":
                    return subj.get("id")
            if t.get("__typename") == "CrossReferencedEvent":
                src = t.get("source", {})
                if src.get("id") and src.get("__typename") == "Issue":
                    return src.get("id")
    except Exception as e:
        logger.error(f"Development Issue 取得に失敗: {e}")
    return None

def get_project_item_map(node_id: str) -> Dict[str, Dict[str, Any]]:
    """指定した node の ProjectV2Item を取得し project_id 毎にまとめる"""
    # Project アイテムとフィールド値を取得する GraphQL クエリ
    query = (
        "query($ID: ID!) {\n"
        "  node(id: $ID) {\n"
        "    ... on Issue {\n"
        "      projectItems(first: 20) {\n"
        "        nodes {\n"
        "          id\n"
        "          project { id title }\n"
        "          fieldValues(first: 50) {\n"
        "            nodes {\n"
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
        "    ... on PullRequest {\n"
        "      projectItems(first: 20) {\n"
        "        nodes {\n"
        "          id\n"
        "          project { id title }\n"
        "          fieldValues(first: 50) {\n"
        "            nodes {\n"
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
    items: Dict[str, Dict[str, Any]] = {}
    try:
        res = run_gh([
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-f", f"ID={node_id}",
        ])
        nodes = (
            json.loads(res)
            .get("data", {})
            .get("node", {})
            .get("projectItems", {})
            .get("nodes", [])
        )
        for n in nodes:
            proj = n.get("project", {})
            pid = proj.get("id")
            if not pid:
                continue
            items[pid] = {
                "project": proj,
                "item": {
                    "id": n.get("id"),
                    "projectId": pid,
                    "fieldValues": n.get("fieldValues", {}).get("nodes", []),
                },
            }
    except Exception as e:
        logger.error(f"Project アイテム取得に失敗: {e}")
    return items

def get_project_field_catalog(project_id: str) -> Dict[str, Dict[str, Any]]:
    """Project のフィールド定義を取得しキャッシュする"""
    if project_id in PROJECT_FIELD_CATALOG_CACHE:
        return PROJECT_FIELD_CATALOG_CACHE[project_id]
    query = (
        "query($PID: ID!) {\n"
        "  node(id: $PID) {\n"
        "    ... on ProjectV2 {\n"
        "      fields(first: 100) {\n"
        "        nodes {\n"
        "          ... on ProjectV2Field { id name dataType }\n"
        "          ... on ProjectV2SingleSelectField { options { id name } }\n"
        "          ... on ProjectV2IterationField { configuration { iterations { id title startDate } } }\n"
        "        }\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    catalog: Dict[str, Dict[str, Any]] = {}
    try:
        res = run_gh([
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-f", f"PID={project_id}",
        ])
        nodes = (
            json.loads(res)
            .get("data", {})
            .get("node", {})
            .get("fields", {})
            .get("nodes", [])
        )
        for n in nodes:
            name = n.get("name")
            if not name:
                continue
            dtype = n.get("dataType")
            meta: Dict[str, Any] = {"fieldId": n.get("id"), "type": dtype}
            if dtype == "SINGLE_SELECT":
                meta["options"] = {o.get("name"): o.get("id") for o in n.get("options", [])}
            elif dtype == "ITERATION":
                iterations = (
                    n.get("configuration", {})
                    .get("iterations", [])
                )
                meta["iterations"] = {i.get("title"): i.get("id") for i in iterations}
            catalog[name] = meta
        PROJECT_FIELD_CATALOG_CACHE[project_id] = catalog
    except Exception as e:
        logger.error(f"Project フィールド取得に失敗: {e}")
    return catalog

def extract_field_value_map(field_values_nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """fieldValues ノードから {フィールド名: 値} マップを生成する"""
    result: Dict[str, Any] = {}
    for fv in field_values_nodes:
        field = fv.get("field", {})
        name = field.get("name")
        if not name:
            continue
        value = (
            fv.get("name")
            or fv.get("date")
            or fv.get("title")
            or fv.get("text")
            or fv.get("number")
        )
        if value is not None:
            result[name] = value
    return result

def update_single_select(project_id: str, item_id: str, field_id: str, option_id: str) -> None:
    """Single-select フィールドを更新する"""
    mutation = (
        "mutation($P:ID!,$I:ID!,$F:ID!,$O:ID!){\n"
        "  updateProjectV2ItemFieldValue(input:{projectId:$P,itemId:$I,fieldId:$F,value:{singleSelectOptionId:$O}}){clientMutationId}\n"
        "}\n"
    )
    try:
        run_gh([
            "gh", "api", "graphql",
            "-f", f"query={mutation}",
            "-f", f"P={project_id}",
            "-f", f"I={item_id}",
            "-f", f"F={field_id}",
            "-f", f"O={option_id}",
        ])
    except Exception as e:
        logger.error(f"Single-select 更新に失敗: {e}")

def update_date(project_id: str, item_id: str, field_id: str, date: str) -> None:
    """Date フィールドを更新する"""
    mutation = (
        "mutation($P:ID!,$I:ID!,$F:ID!,$D:Date!){\n"
        "  updateProjectV2ItemFieldValue(input:{projectId:$P,itemId:$I,fieldId:$F,value:{date:$D}}){clientMutationId}\n"
        "}\n"
    )
    try:
        run_gh([
            "gh", "api", "graphql",
            "-f", f"query={mutation}",
            "-f", f"P={project_id}",
            "-f", f"I={item_id}",
            "-f", f"F={field_id}",
            "-f", f"D={date}",
        ])
    except Exception as e:
        logger.error(f"Date 更新に失敗: {e}")

def update_iteration(project_id: str, item_id: str, field_id: str, iteration_id: str) -> None:
    """Iteration フィールドを更新する"""
    mutation = (
        "mutation($P:ID!,$I:ID!,$F:ID!,$T:ID!){\n"
        "  updateProjectV2ItemFieldValue(input:{projectId:$P,itemId:$I,fieldId:$F,value:{iterationId:$T}}){clientMutationId}\n"
        "}\n"
    )
    try:
        run_gh([
            "gh", "api", "graphql",
            "-f", f"query={mutation}",
            "-f", f"P={project_id}",
            "-f", f"I={item_id}",
            "-f", f"F={field_id}",
            "-f", f"T={iteration_id}",
        ])
    except Exception as e:
        logger.error(f"Iteration 更新に失敗: {e}")

def sync_if_empty_same_project(pr_item: Dict[str, Any], issue_item: Dict[str, Any], field_catalog: Dict[str, Dict[str, Any]]) -> None:
    """PR 側が空欄の場合に Issue 側の値をコピーする"""
    want = ["Priority", "Target Date", "Sprint"]
    pr_map = extract_field_value_map(pr_item.get("fieldValues", []))
    issue_map = extract_field_value_map(issue_item.get("fieldValues", []))
    for fname in want:
        pr_v = pr_map.get(fname)
        issue_v = issue_map.get(fname)
        if (pr_v is None or pr_v == "") and issue_v:
            fmeta = field_catalog.get(fname)
            if not fmeta:
                continue
            if fmeta["type"] == "SINGLE_SELECT":
                opt_id = fmeta.get("options", {}).get(issue_v)
                if opt_id:
                    update_single_select(pr_item["projectId"], pr_item["id"], fmeta["fieldId"], opt_id)
            elif fmeta["type"] == "DATE":
                update_date(pr_item["projectId"], pr_item["id"], fmeta["fieldId"], issue_v)
            elif fmeta["type"] == "ITERATION":
                it_id = fmeta.get("iterations", {}).get(issue_v)
                if it_id:
                    update_iteration(pr_item["projectId"], pr_item["id"], fmeta["fieldId"], it_id)

def get_assignee_user_ids_for_pr(pr_node_id: str) -> List[str]:
    """PR のアサイン済みユーザー ID を取得する"""
    query = (
        "query($ID:ID!){ node(id:$ID){ ... on PullRequest { assignees(first:100){ nodes { id } } } } }"
    )
    try:
        res = run_gh([
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-f", f"ID={pr_node_id}",
        ])
        nodes = (
            json.loads(res)
            .get("data", {})
            .get("node", {})
            .get("assignees", {})
            .get("nodes", [])
        )
        return [n.get("id") for n in nodes if n.get("id")]
    except Exception as e:
        logger.error(f"PR アサイン取得に失敗: {e}")
        return []

def get_assignee_user_ids_for_issue(issue_node_id: str) -> List[str]:
    """Issue のアサイン済みユーザー ID を取得する"""
    query = (
        "query($ID:ID!){ node(id:$ID){ ... on Issue { assignees(first:100){ nodes { id } } } } }"
    )
    try:
        res = run_gh([
            "gh", "api", "graphql",
            "-f", f"query={query}",
            "-f", f"ID={issue_node_id}",
        ])
        nodes = (
            json.loads(res)
            .get("data", {})
            .get("node", {})
            .get("assignees", {})
            .get("nodes", [])
        )
        return [n.get("id") for n in nodes if n.get("id")]
    except Exception as e:
        logger.error(f"Issue アサイン取得に失敗: {e}")
        return []

def add_assignees_to_assignable(assignable_id: str, user_ids: List[str]) -> None:
    """指定した assignable にユーザーをアサインする"""
    mutation = (
        "mutation($A:ID!,$U:[ID!]!){ addAssigneesToAssignable(input:{assignableId:$A,assigneeIds:$U}){clientMutationId} }"
    )
    try:
        run_gh([
            "gh", "api", "graphql",
            "-f", f"query={mutation}",
            "-f", f"A={assignable_id}",
            # assigneeIds には JSON 配列をそのまま渡す
            "-f", f"U={json.dumps(user_ids)}",
        ])
    except Exception as e:
        logger.error(f"アサイン追加に失敗: {e}")

def sync_pr_assignees_if_empty_from_issue(pr_node_id: str, issue_node_id: str) -> None:
    """PR にアサインが無い場合 Issue のアサインをコピーする"""
    pr_assignees = get_assignee_user_ids_for_pr(pr_node_id)
    if pr_assignees:
        return
    issue_assignees = get_assignee_user_ids_for_issue(issue_node_id)
    if issue_assignees:
        add_assignees_to_assignable(pr_node_id, issue_assignees)

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
    # 出力ファイル名を <リポジトリ名>_PR_status.md 形式で生成
    output_file = os.path.join(output_dir, f"{file_suffix}_PR_status.md")

    # 環境変数 LOGIN_USERS_B64 をデコードしてユーザーと組織の対応表を作成
    login_user_map: Dict[str, str] = {}
    org_order: List[str] = []
    required_reviewers: Set[str] = set()
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
                required = item.get("requiredReviewer")
                if login and org:
                    login_user_map[login] = org
                    if org not in org_order:
                        org_order.append(org)
                    if required:
                        required_reviewers.add(login)
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

        pr_status = determine_pr_status(reviewer_states, is_draft, required_reviewers)

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

        # PR 情報収集後に Issue との同期処理を実行
        try:
            issue_id = get_first_development_issue_id(pr_node_id)
            if issue_id:
                pr_items = get_project_item_map(pr_node_id)
                issue_items = get_project_item_map(issue_id)
                for pid, pr_item in pr_items.items():
                    issue_item = issue_items.get(pid)
                    if not issue_item:
                        continue
                    catalog = get_project_field_catalog(pid)
                    sync_if_empty_same_project(pr_item["item"], issue_item["item"], catalog)
                sync_pr_assignees_if_empty_from_issue(pr_node_id, issue_id)
        except Exception as e:
            logger.error(f"同期処理に失敗: {e}")

    logger.info(f"PR 情報を {output_file} に出力しました")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PR 情報を収集して Markdown に出力します")
    parser.add_argument("output_dir", nargs="?", default=".")
    parser.add_argument("--repo", help="対象とするリポジトリ (owner/name)", default="")
    args = parser.parse_args()
    main(args.output_dir, args.repo)
