# PR チェックワークフロー

このワークフローは開いているプルリクエストの状況を Wiki にまとめる。

## トリガー条件
- `workflow_dispatch`: 手動実行。
- `push`: `.github/workflows/pr-check.yaml` または `.github/workflows/script/collect_pr_status.py` が更新されたとき。

## 実行環境
- GitHub Actions で `ubuntu-latest` を使用。

## 各ステップでの処理内容
1. `actions/checkout@v4` でリポジトリを取得。
2. `checkout-wiki` で Wiki リポジトリをチェックアウト（存在しなくてもエラーにならない）。
3. `pr-check` ステップでは、環境変数 `GH_TOKEN`, `LOG_LEVEL`, `LOGIN_USERS_B64`, `SUB_REPOSITORY` を利用し、`.github/workflows/script/collect_pr_status.py` を実行して各リポジトリの PR 情報を Markdown にまとめる。
4. `update-wiki` ステップでは、Wiki のチェックアウトが成功した場合のみ `.github/workflows/script/update_wiki.py` を実行し、生成された Markdown を Wiki にコミット・プッシュする。

## 環境変数
- `GH_TOKEN`: GitHub CLI 認証に使用。
- `LOG_LEVEL`: スクリプトのログ出力レベル。
- `LOGIN_USERS_B64`: レビュー必須ユーザーなどを含む設定を Base64 でエンコードした文字列。
- `SUB_REPOSITORY`: 追加でチェックするサブリポジトリの一覧（空白や改行区切り）。
- `GITHUB_TOKEN`: Wiki リポジトリに push するときに使用。

## 関連スクリプト
- `.github/workflows/script/collect_pr_status.py`: GitHub CLI を利用して開いている PR の情報（レビュー状態や Projects のフィールドなど）を収集し、Wiki 向け Markdown を生成する。
- `.github/workflows/script/update_wiki.py`: 生成された `PR_Status*.md` を Wiki リポジトリにコミット・プッシュする。差分がない場合は更新しない。

## Wiki 更新条件
`checkout-wiki` ステップが成功し、かつ `PR_Status*.md` に変更がある場合のみ `update_wiki.py` がコミットと push を行う。
