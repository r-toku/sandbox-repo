#!/usr/bin/env python3
"""PR 情報を記載した Markdown を Wiki リポジトリへ反映するスクリプト

1. GitHub Actions から渡されたトークンを使って push 可能なリモート URL を設定
2. `PR_Status.md` の変更をステージングし、差分があればコミット・プッシュ
3. 変更がない場合は何もせず終了する
"""
import os
import subprocess
import sys
import logging

# 環境変数 LOG_LEVEL を参照してログレベルを設定
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

def run(cmd):
    """サブプロセスでコマンドを実行しエラー時には例外を送出する"""
    subprocess.run(cmd, check=True)

def main(wiki_dir: str) -> None:
    """指定された Wiki ディレクトリに移動しファイルをコミット・プッシュする"""
    os.chdir(wiki_dir)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        repo = os.environ.get("GITHUB_REPOSITORY")
        # 認証付き URL に差し替えて push 可能にする
        run([
            "git",
            "remote",
            "set-url",
            "origin",
            f"https://x-access-token:{token}@github.com/{repo}.wiki.git",
        ])

    if not os.path.exists("PR_Status.md"):
        logger.error("PR_Status.md が見つかりません")
        sys.exit(1)

    # 差分があればコミットしてプッシュする
    run(["git", "add", "PR_Status.md"])
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode != 0:
        actor = os.environ.get("GITHUB_ACTOR", "github-actions")
        run(["git", "config", "user.name", actor])
        run(["git", "config", "user.email", f"{actor}@users.noreply.github.com"])
        run(["git", "commit", "-m", "Update PR status"])
        run(["git", "push"])
    else:
        logger.info("更新内容がないためコミットしません")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        logger.error("Wiki リポジトリのパスを指定してください")
        sys.exit(1)
    main(sys.argv[1])
