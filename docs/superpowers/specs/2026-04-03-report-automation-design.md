# 月次レポート自動生成パイプライン 設計書

## 概要

BirdXplorer の RDS から月次の日本語コミュニティノートを抽出し、kouchou-ai で AI 分析を実行し、静的HTMLレポートを生成して BirdXplorer_Viewer リポジトリに PR を自動作成するパイプライン。

## 背景

- 現在、月次レポートは手動で作成している（DB 抽出 → kouchou-ai 分析 → HTML書き出し → Viewer にコピー → PR 作成）
- 2026年2月レポートの手動作成で全ステップのパラメータが確定済み
- 既存の BirdXplorer AWS インフラ（ECS Fargate, EventBridge, VPC, RDS）に組み込む

## アーキテクチャ

### 全体構成

```
EventBridge (毎月3日 06:00 UTC = 15:00 JST)
    ↓
ECS Fargate タスク (report-generator)
    ┌──────────────────────────────────────────┐
    │ Container 1: orchestrator (メイン)        │
    │   Python スクリプト                       │
    │   - RDS接続 → CSV生成                    │
    │   - kouchou-ai API呼び出し               │
    │   - 静的ビルド取得                        │
    │   - GitHub API で PR作成                  │
    │                                          │
    │ Container 2: kouchou-ai-api (sidecar)     │
    │   apps/api (port 8000)                   │
    │                                          │
    │ Container 3: static-site-builder (sidecar)│
    │   apps/static-site-builder (port 3200)   │
    └──────────────────────────────────────────┘
```

### コンテナ間通信

ECS Fargate のマルチコンテナタスクでは、コンテナ間は `localhost` で通信可能。orchestrator から `localhost:8000`（kouchou-ai API）と `localhost:3200`（static-site-builder）にアクセスする。

## コンポーネント詳細

### Container 1: orchestrator（メインコンテナ）

- **言語**: Python 3.12
- **配置**: `BirdXplorer/etl/src/birdxplorer_etl/scripts/report_generator.py`
- **ECR リポ**: `birdxplorer-report-generator`
- **Docker イメージ**: Python 3.12 slim + psycopg2 + requests
- **essential**: true（このコンテナの終了でタスク全体が停止）

**処理フロー:**

1. サイドカー起動待ち: `localhost:8000` と `localhost:3200` のヘルスチェックをリトライ（最大60秒）
2. RDS に接続し、前月の日本語ノートを抽出
   - テーブル: `notes`
   - 条件: `language = 'ja' AND created_at >= {start_millis} AND created_at < {end_millis}`
   - 出力: `/tmp/report.csv`（`comment-id`, `comment-body` カラム）
3. kouchou-ai API にレポート作成リクエスト（`POST localhost:8000/admin/reports`）
4. ステータスをポーリング（`GET /admin/reports/{slug}/status/step-json`）、完了まで待機（タイムアウト: 60分）
5. レポートの公開設定を変更（公開に設定）
6. 静的ビルドリクエスト（`POST localhost:3200/build` body: `{"slugs": "{slug}"}`）→ zip 取得
7. zip を展開し、GitHub API で BirdXplorer_Viewer リポに PR 作成

### Container 2: kouchou-ai-api（サイドカー）

- **イメージ**: BirdXplorer_kouchou-ai の `apps/api` Docker イメージ
- **ECR リポ**: `birdxplorer-kouchou-ai-api`
- **ポート**: 8000
- **essential**: false
- **環境変数**:
  - `OPENAI_API_KEY`: Secrets Manager から取得
  - `ADMIN_API_KEY`: `admin`
  - `PUBLIC_API_KEY`: `public`
  - `STORAGE_TYPE`: `local`
  - `ENVIRONMENT`: `production`

### Container 3: static-site-builder（サイドカー）

- **イメージ**: BirdXplorer_kouchou-ai の `apps/static-site-builder` Docker イメージ
- **ECR リポ**: `birdxplorer-kouchou-ai-static-builder`
- **ポート**: 3200
- **essential**: false
- **環境変数**:
  - `NEXT_PUBLIC_STATIC_EXPORT_BASE_PATH`: orchestrator がビルドリクエスト時に指定（`/kouchou-ai/YYYY/MM`）
  - `NEXT_PUBLIC_API_BASEPATH`: `http://localhost:8000`
  - `API_BASEPATH`: `http://localhost:8000`
  - `NEXT_PUBLIC_PUBLIC_API_KEY`: `public`

## 日付計算ロジック

```python
from datetime import datetime, timezone

now = datetime.now(timezone.utc)
first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

if first_of_this_month.month == 1:
    start = first_of_this_month.replace(year=first_of_this_month.year - 1, month=12)
else:
    start = first_of_this_month.replace(month=first_of_this_month.month - 1)
end = first_of_this_month

start_millis = int(start.timestamp() * 1000)
end_millis = int(end.timestamp() * 1000)
target_year = start.year
target_month = start.month
```

例: 2026-04-03 実行 → 2026-03-01 00:00:00 UTC 〜 2026-04-01 00:00:00 UTC を対象

## kouchou-ai API 呼び出しパラメータ

```python
# POST /admin/reports
{
    "input": slug,
    "question": f"{target_year}年 {target_month}月レポート",
    "intro": "",
    "comments": [{"id": row["comment-id"], "comment": row["comment-body"]} for row in csv_rows],
    "cluster": [20, 100],
    "provider": "openai",
    "model": "gpt-4o-mini",
    "workers": 30,
    "prompt": {
        "extraction": "あなたは専門的なリサーチアシスタントです。...",
        "initial_labelling": "あなたはKJ法が得意なデータ分析者です。...",
        "merge_labelling": "あなたはデータ分析のエキスパートです。...",
        "overview": "あなたはシンクタンクで働く専門のリサーチアシスタントです。..."
    }
}
```

プロンプトのデフォルト値は kouchou-ai 管理画面のデフォルトと同じものを使用する。

## GitHub PR 作成

GitHub REST API v3 で以下を実行:

1. `dev` ブランチの最新 SHA を取得
2. `feat/add-report-YYYYMM` ブランチを作成
3. 静的ファイルを `public/kouchou-ai/YYYY/MM/` に配置（zip 内の全ファイルをツリーAPIでコミット）
4. `app/data/reports.ts` に新レポートエントリを追加
5. `app/routes/_index.tsx` のトップページ iframe src を新レポートのパスに更新
6. PR 作成（base: `dev`）

**PR テンプレート:**
```
## 概要
{target_year}年 {target_month}月の広聴AIレポートを追加

## 自動生成
このPRは月次レポート自動生成パイプラインにより作成されました。

## 検証チェックリスト
- [ ] レポートページでチャートが正しく表示される
- [ ] トップページの広聴AIセクションが更新されている
- [ ] クラスタ情報が表示される
```

## インフラ変更（BirdXplorer-cdk）

### 新規リソース

- **ECS タスク定義**: `{stage}ReportGeneratorTaskDef`
  - CPU: 2048, Memory: 4096 MiB
  - 3 コンテナ（orchestrator, kouchou-ai-api, static-site-builder）
  - サブネット: パブリック（RDS アクセス + インターネットアクセス）
  - セキュリティグループ: `sgForBirdXplorerService`
- **EventBridge ルール**: 毎月3日 06:00 UTC（`cron(0 6 3 * ? *)`）
- **ECR リポジトリ**: 3つ追加
  - `birdxplorer-report-generator`
  - `birdxplorer-kouchou-ai-api`
  - `birdxplorer-kouchou-ai-static-builder`
- **CloudWatch ロググループ**: `/ecs/{stage}-report-generator`

### 既存リソースの変更

- **Secrets Manager** (`{stage}-bird-xplorer-etl-secrets`): `GITHUB_TOKEN` と `OPENAI_API_KEY` を追加
- **config/dev.json**: ECR リポジトリ名を追加
- **config/prd.json**: 同上（prd 適用時）

### IAM ロール

既存の `BackendTaskRole` を再利用。追加権限:
- Secrets Manager の読み取り（既存）
- SQS は不要（このタスクはキューを使わない）
- S3 も不要（GitHub API 経由で直接 PR 作成）

## エラーハンドリング

| エラー | 対応 |
|-------|------|
| サイドカー起動タイムアウト（60秒） | タスク失敗 → CloudWatch ログ → SNS/Slack 通知 |
| RDS 接続失敗 | リトライ3回 → タスク失敗 |
| kouchou-ai 分析タイムアウト（60分） | タスク失敗 → ログに最終ステータス出力 |
| kouchou-ai 分析エラー | タスク失敗 → ログにエラー詳細出力 |
| 静的ビルド失敗 | リトライ3回 → タスク失敗 |
| GitHub API 失敗 | リトライ3回 → タスク失敗 |
| 対象月のノートが0件 | 正常終了（PR は作成しない、ログに記録） |

全てのタスク失敗は既存の MonitoringStack の SNS/Slack 通知に乗せる。

## ローカルテスト

### 前提条件

- BirdXplorer_kouchou-ai の `docker compose up` が動作すること
- dev RDS への接続が可能であること（SSM ポートフォワーディングまたは直接接続）

### テスト手順

```bash
# 1. kouchou-ai を起動
cd /path/to/BirdXplorer_kouchou-ai
docker compose up -d api static-site-builder

# 2. orchestrator を dry-run で実行
cd /path/to/BirdXplorer/etl
python -m birdxplorer_etl.scripts.report_generator \
  --db-host <dev-rds-host> \
  --db-port 5432 \
  --db-user <user> \
  --db-pass <pass> \
  --db-name postgres \
  --kouchou-api-url http://localhost:8000 \
  --static-builder-url http://localhost:3200 \
  --target-year 2026 \
  --target-month 2 \
  --dry-run

# 3. 出力確認
# - /tmp/report-YYYYMM.csv が生成される
# - /tmp/report-YYYYMM.zip が生成される
# - reports.ts の差分がコンソールに出力される
# - GitHub PR は作成されない

# 4. 通しテスト（GitHub PR 作成まで）
python -m birdxplorer_etl.scripts.report_generator \
  --db-host <dev-rds-host> \
  ... \
  --github-token <token> \
  --github-repo codeforjapan/BirdXplorer_Viewer
```

### dry-run モード

`--dry-run` フラグを付けると:
- DB 抽出: 実行する（CSV 出力）
- kouchou-ai 分析: 実行する
- 静的ビルド: 実行する（zip をローカル出力）
- GitHub PR: **スキップ**（差分のプレビューのみコンソール出力）

### 月指定オプション

`--target-year` と `--target-month` で対象月を明示的に指定可能。省略時は前月を自動計算。

## ファイル構成

```
BirdXplorer/
└── etl/
    └── src/birdxplorer_etl/
        └── scripts/
            ├── report_generator.py     # メインスクリプト
            ├── report_db.py            # DB 抽出ロジック
            ├── report_kouchou.py       # kouchou-ai API クライアント
            ├── report_github.py        # GitHub API クライアント
            └── report_templates.py     # reports.ts / _index.tsx テンプレート

BirdXplorer-cdk/
├── lib/
│   └── bird_xplorer-stack.ts          # ECS タスク定義追加
└── config/
    ├── dev.json                        # ECR リポ追加
    └── prd.json                        # 同上
```

## 対象外（今回のスコープ外）

- PR の自動マージ（PR 作成まで。マージは人が確認）
- prd 環境への適用（まず dev で検証）
- レポート内容のカスタマイズ UI
- 過去月の一括生成（手動で `--target-year/month` 指定で対応可能）
