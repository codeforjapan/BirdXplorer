# パフォーマンス計測基盤

API のレスポンス時間を計測してベースラインを把握するための仕組み。
KPI 設定（応答時間 SLO、期間フィルタの許容範囲、検索スループット）の
現在値を出す目的で導入する。

## 構成

1. `TimingMiddleware`（`api/birdxplorer_api/middlewares/timing.py`）
   - すべての HTTP リクエストの所要時間を計測する ASGI middleware
   - 1 リクエストにつき `request_timing` という構造化ログ 1 行を出力
   - レスポンスに `X-Response-Time-ms` ヘッダを付与
2. ベンチマークスクリプト（`scripts/perf/bench_api.py`）
   - 代表クエリ（`scripts/perf/scenarios.json`）を逐次実行
   - 1 シナリオあたり warmup → 計測 N 回 → CSV 出力
   - 同時実行は 1（KPI の前提と一致）

## ログの読み方

`TimingMiddleware` が出力するログの 1 行例（実体は 1 行 JSON、見やすさのため整形）:

```json
{
  "message": "request_timing",
  "time": "2026-05-15T00:45:07.043270+00:00",
  "method": "GET",
  "path": "/api/v1/data/notes",
  "status_code": 200,
  "duration_ms": 412.531,
  "filter_params": {
    "created_at_from": "1733097600000",
    "created_at_to": "1735689600000",
    "limit": "100"
  },
  "period_days": 30
}
```

主なフィールド:

| フィールド | 意味 |
| --- | --- |
| `duration_ms` | リクエスト処理に要した時間（ミリ秒）。middleware 受け取りからレスポンス送信完了までの実時間 |
| `path` | URL パス（クエリ文字列は除く） |
| `status_code` | HTTP ステータス |
| `filter_params` | KPI に影響する代表的クエリパラメータのみ抜粋（`start_date`, `end_date`, `created_at_from`, `created_at_to`, `limit`, `offset`, `topic_ids`, `current_status`, `language`, `search_text`） |
| `period_days` | `start_date`/`end_date` または `created_at_*` が ISO 日付で与えられた時のみ。日数（end - start） |

`X-Response-Time-ms` レスポンスヘッダも同じ値を ASCII 文字列で持つ。
ロードバランサや API Gateway のアクセスログと突き合わせる用途を想定。

### ログの集計例

CloudWatch Logs Insights:

```
fields @timestamp, path, status_code, duration_ms, period_days
| filter message = "request_timing"
| stats avg(duration_ms), pct(duration_ms, 50) as p50, pct(duration_ms, 95) as p95, count() by path
```

jq（ローカルログファイル）:

```
cat api.log \
  | jq -c 'select(.message=="request_timing") | {path, status_code, duration_ms, period_days}' \
  | sort | uniq -c | sort -rn | head
```

## ベンチマークの実行

前提: API が起動済み（`http://localhost:8000` などで疎通可能）、本番に近いデータが入っていること。

```bash
# 依存（httpx は api/[dev] に含まれる）
pip install -e api/[dev]

# 既定シナリオで 5 回計測（warmup 1 回 + 計測 5 回）
python scripts/perf/bench_api.py \
  --base-url http://localhost:8000 \
  --iterations 5 \
  --output perf-results-$(date +%Y%m%d).csv
```

標準出力にシナリオごとの集計 JSON が出る:

```json
[
  {
    "scenario": "data/notes - 30d",
    "runs": 5,
    "success": 5,
    "statuses": [200],
    "p50_ms": 312.5,
    "p95_ms": 410.2,
    "max_ms": 415.6,
    "mean_ms": 340.1
  }
]
```

CSV には 1 リクエスト 1 行で生データが残る（`duration_ms` はクライアント側計測、`server_ms` は `X-Response-Time-ms` ヘッダ値）。
クライアント側時間 - サーバ側時間が大きく開く場合はネットワーク／逆プロキシ要因の切り分け材料。

### シナリオの追加・修正

`scripts/perf/scenarios.json` を編集する。1 要素は次のスキーマ:

```json
{
  "name": "任意の表示名",
  "method": "GET",
  "path": "/api/v1/data/notes",
  "params": { "createdAtFrom": "1733097600000", "limit": "100" }
}
```

`method` 省略時は `GET`。

### スループット要件

要件として「同時ユーザー 1 〜 数人」を想定しているため、本スクリプトは
**逐次 1 並列のみ**。並列負荷をかけたい場合は別途 `locust` 等を使う。

## ベースライン計測手順（KPI 設定の前段）

1. 本番に近い DB を持つステージング環境で API を起動
2. 上記コマンドで `iterations=5`、`warmup=1` を最低 1 セット
3. 出力 CSV を `perf/results/<YYYYMMDD>-<env>.csv` として保存（コミット不要）
4. 集計 JSON を `docs/perf-baseline-<YYYYMMDD>.md` などに転記し、KPI 目標値検討の材料にする

## 既知の限界

- middleware は ASGI lifespan を計測しない（HTTP リクエストのみ）
- `duration_ms` は middleware → ハンドラ → middleware の往復時間で、Uvicorn のソケット受信〜送信完了までは含まない（実 RTT より短く出る）。本格的に網羅したい場合は ALB / API Gateway 側のメトリクスと併用する
- ローカル `TestClient` 経由ではネットワーク要因がほぼ 0 になるため、現実値とのギャップに留意する
