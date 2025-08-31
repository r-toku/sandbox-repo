#!/usr/bin/env python3
"""PR 情報を記載した Markdown を Wiki リポジトリへ反映するスクリプト

1. GitHub Actions から渡されたトークンを使って push 可能なリモート URL を設定
2. `<リポジトリ名>_PR_status.md` の変更をステージングし、差分があればコミット・プッシュ
3. 変更がない場合は何もせず終了する
"""
import os
import subprocess
import sys

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

    repo_name = os.environ.get("REPOSITORY_NAME")
    if not repo_name:
        repo_name = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] or "repository"
    file_name = f"{repo_name}_PR_status.md"
    # リポジトリ名を用いたファイルを確認しステージングする
    if not os.path.exists(file_name):
        print(f"{file_name} が見つかりません")
        sys.exit(1)

    # 差分があればコミットしてプッシュする
    run(["git", "add", file_name])
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode != 0:
        actor = os.environ.get("GITHUB_ACTOR", "github-actions")
        run(["git", "config", "user.name", actor])
        run(["git", "config", "user.email", f"{actor}@users.noreply.github.com"])
        run(["git", "commit", "-m", f"Update {repo_name} PR status"])
        run(["git", "push"])
    else:
        print("更新内容がないためコミットしません")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Wiki リポジトリのパスを指定してください", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
