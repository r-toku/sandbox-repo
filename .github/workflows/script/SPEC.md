# スクリプト仕様書

## pr-check.yaml
- `collect_pr_status.py` と `update_wiki.py` を実行する GitHub Actions ワークフロー。
- 環境変数 `LOGIN_USERS_B64` にレビュワーと所属組織の対応表を Base64 文字列として設定する。
- 環境変数 `LOG_LEVEL` を指定してスクリプトのログレベルを制御する。
- `GH_TOKEN` には `GH_PROJECT_PAT` を渡し、収集と同期を同一トークンで実行する。

## collect_pr_status.py
- GitHub CLI (`gh`) を利用してオープン中の PR 情報と Projects (v2) のフィールド値を取得し、`<リポジトリ名>_PR_status.md` を生成する。
- レビュー履歴を `submittedAt` 昇順で集計し、レビュー再依頼中のレビュワーは「保留 (⏳)」とする。PR ステータスは「ドラフト/未レビュー/修正依頼/承認済み/レビュー中」を判定する。
- 環境変数 `LOGIN_USERS_B64` を Base64 デコードし、レビュワーの所属組織を解決して列を動的生成する。未定義ユーザーは `other` に分類。
- 出力列: PR, Title, 状態, <各組織 Reviewers>, Assignees, Status, Priority, Target Date, Sprint。
- `--repo` で対象リポジトリを指定可能。`LOG_LEVEL` でログレベル制御。

### Issue → PR 同期仕様（Development 連携）
- 対象: PR と Development に紐づく最初の Issue（`closingIssuesReferences` または `Connected/CrossReferenced`）。
- 同一 Project 内で、PR 側が未設定のときのみ Issue の値をコピーする。未設定判定は `None/""/"No Status"/"None"/"-"/"未設定"`（大文字小文字・空白は無視）。
- 対象フィールドと更新方法:
  - Status（Single‑select）: オプション名で一致（大文字小文字・空白を無視して再マッチ）。`singleSelectOptionId`（String!）で更新。
  - Priority（Single‑select）: 同上。
  - Target Date（Date）: そのまま日付文字列で更新。
  - Sprint（Iteration）: カタログの `title → iterationId` で解決。見つからない場合は Issue 側のフィールド値ノードから `iterationId` をフォールバックで使用。`iterationId`（String!）で更新。
- Assignees 同期: PR にアサインが無い場合、Issue のアサイン（User ノード ID）を PR にコピー。GraphQL ミューテーションは値をクエリへ直接埋め込み（配列の文字列化問題を回避）。

### 例外・制約
- Sprint の `iterationId` は同一 Project 上のフィールドに対してのみ有効。他プロジェクトのイテレーション ID は適用不可。
- Project のフィールドやオプションが存在しない場合はスキップする。
- `gh` コマンドに失敗した場合はエラーログを出しつつ処理継続（可能な範囲で他項目を処理）。

### ロギング（DEBUG 時）
- Project フィールドカタログの要約（型/オプション/イテレーション）を出力。
- 同期前後で PR/Issue のフィールドマップ、個別フィールドの空判定、更新/スキップ理由を出力。

## update_wiki.py
- 指定された Wiki リポジトリに移動し、`*_PR_status.md` の変更をコミットしてプッシュする。
- `GITHUB_TOKEN` を用いた認証 URL に差し替えることで push を可能にする。
- 差分がない場合はコミットやプッシュを行わず終了する。
- `LOG_LEVEL` 環境変数を利用して logging モジュールの出力レベルを制御する。

## pr-check.yaml
- 環境変数 `SUB_REPOSITORY` にスペースまたは改行で区切った複数のリポジトリを指定できる。
- メインリポジトリと指定した全サブリポジトリの PR ステータスを順に収集する。
