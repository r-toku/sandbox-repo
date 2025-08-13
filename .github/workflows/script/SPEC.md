# スクリプト仕様書

## pr-check.yaml
- `collect_pr_status.py` と `update_wiki.py` を実行する GitHub Actions ワークフロー。
- 環境変数 `LOGIN_USERS_B64` にレビュワーと所属組織の対応表を Base64 文字列として設定する。
- 環境変数 `LOG_LEVEL` を指定してスクリプトのログレベルを制御する。

## collect_pr_status.py
- GitHub CLI (`gh`) を利用してオープン中の PR 情報と Projects (v2) のフィールド値を取得する。
- レビュー履歴を `submittedAt` で昇順ソートし、再依頼されたレビューは「保留」に戻す。
- 取得した情報を `<リポジトリ名>_PR_status.md` として Markdown 形式で出力する。
- 環境変数 `LOGIN_USERS_B64` を Base64 デコードしてユーザーと所属組織の対応表を作成し、レビュワーを組織ごとに分類する。リストに存在しないユーザーは `other` として扱う。
- 出力する列: PR, Title, 状態, Assignees, Status, Priority, Target Date, Sprint、および各組織ごとの Reviewers 列。
- `LOG_LEVEL` 環境変数を利用して logging モジュールの出力レベルを制御する。
- レビュワーごとの最新ステータスを集計し、再依頼されたレビューは「保留」に戻す。
- `--repo` 引数で対象リポジトリを指定し、リポジトリごとに `<owner>_<repo>_PR_status.md` を出力する。
- 出力する列: PR, Title, 状態, Reviewers, Assignees, Status, Priority, Target Date, Sprint。
- 事前に `gh` コマンドが利用可能であること。

## update_wiki.py
- 指定された Wiki リポジトリに移動し、`*_PR_status.md` の変更をコミットしてプッシュする。
- `GITHUB_TOKEN` を用いた認証 URL に差し替えることで push を可能にする。
- 差分がない場合はコミットやプッシュを行わず終了する。
- `LOG_LEVEL` 環境変数を利用して logging モジュールの出力レベルを制御する。

## pr-check.yaml
- 環境変数 `SUB_REPOSITORY` にスペースまたは改行で区切った複数のリポジトリを指定できる。
- メインリポジトリと指定した全サブリポジトリの PR ステータスを順に収集する。
