#!/usr/bin/env python3
"""Wiki リポジトリを更新するスクリプト"""
import os
import subprocess
import sys

# コマンドを実行するユーティリティ
def run(cmd):
    subprocess.run(cmd, check=True)

def main(wiki_dir: str) -> None:
    os.chdir(wiki_dir)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        repo = os.environ.get("GITHUB_REPOSITORY")
        run([
            "git",
            "remote",
            "set-url",
            "origin",
            f"https://x-access-token:{token}@github.com/{repo}.wiki.git",
        ])

    if not os.path.exists("PR_Status.md"):
        print("PR_Status.md が見つかりません")
        sys.exit(1)

    run(["git", "add", "PR_Status.md"])
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode != 0:
        actor = os.environ.get("GITHUB_ACTOR", "github-actions")
        run(["git", "config", "user.name", actor])
        run(["git", "config", "user.email", f"{actor}@users.noreply.github.com"])
        run(["git", "commit", "-m", "Update PR status"])
        run(["git", "push"])
    else:
        print("更新内容がないためコミットしません")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Wiki リポジトリのパスを指定してください", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
