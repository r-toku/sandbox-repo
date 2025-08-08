# スクリプト仕様書

## collect_pr_status.py
- GitHub CLI (`gh`) を利用してオープン中の PR 情報と Projects (v2) のフィールド値を取得する。
- レビュワーごとの最新ステータスを集計し、再依頼されたレビューは「保留」に戻す。
- `--repo` 引数で対象リポジトリを指定し、リポジトリごとに `PR_Status_<owner>_<repo>.md` を出力する。
- 出力する列: PR, Title, 状態, Reviewers, Assignees, Status, Priority, Target Date, Sprint。
- 事前に `gh` コマンドが利用可能であること。

## update_wiki.py
- 指定された Wiki リポジトリに移動し、`PR_Status*.md` の変更をコミットしてプッシュする。
- `GITHUB_TOKEN` を用いた認証 URL に差し替えることで push を可能にする。
- 差分がない場合はコミットやプッシュを行わず終了する。

## pr-check.yaml
- 環境変数 `SUB_REPOSITORY` にスペースまたは改行で区切った複数のリポジトリを指定できる。
- メインリポジトリと指定した全サブリポジトリの PR ステータスを順に収集する。
