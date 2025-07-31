# etl/Dockerfile.tweet コンテナ動作確認計画

## 概要
`etl/Dockerfile.tweet`は、AWS Lambda Container Image用のDockerfileで、X（Twitter）のツイート情報を取得してPostgreSQLデータベースに保存する`postlookup_lambda.py`を実行するコンテナです。

## コンテナの機能
- X API v2を使用してツイート情報を取得
- ユーザー情報、メディア情報、URL情報も含めて取得
- PostgreSQLデータベースに以下のテーブルにデータを保存：
  - `row_users` (ユーザー情報)
  - `row_posts` (ツイート情報)
  - `row_post_media` (メディア情報)
  - `row_post_embed_urls` (埋め込みURL情報)

## 動作確認手順

### 1. 環境準備

#### PostgreSQLコンテナの起動
```bash
# PostgreSQLコンテナを起動
docker run -d \
  --name postgres-test \
  -e POSTGRES_PASSWORD=birdxplorer \
  -e POSTGRES_DB=birdxplorer \
  -p 5432:5432 \
  postgres:13
```

#### 環境変数の設定
```bash
# .env.test ファイルを作成
cat > .env.test << EOF
X_BEARER_TOKEN=your_actual_bearer_token_here
DB_HOST=host.docker.internal
DB_PORT=5432
DB_USER=postgres
DB_PASS=birdxplorer
DB_NAME=birdxplorer
EOF
```

### 2. Dockerイメージのビルド
```bash
# プロジェクトルートディレクトリで実行
docker build -f etl/Dockerfile.tweet -t birdxplorer-tweet-lambda .
```

### 3. Lambda Runtime Interface Emulatorでの起動
```bash
# コンテナを起動（ポート9000でLambda RIEを公開）
docker run -d \
  --name tweet-lambda-test \
  -p 9000:8080 \
  --env-file .env.test \
  birdxplorer-tweet-lambda
```

### 4. テスト実行

#### 正常ケース: 有効なツイートIDでのテスト
```bash
# 有効なツイートIDでテスト（例: 実際に存在するツイートID）
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
    "tweet_id": "1234567890123456789"
  }'
```

#### エラーケース: 無効なツイートIDでのテスト
```bash
# 存在しないツイートIDでテスト
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
    "tweet_id": "invalid_tweet_id"
  }'
```

#### エラーケース: tweet_idパラメータなしでのテスト
```bash
# tweet_idパラメータなしでテスト
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
    "other_param": "value"
  }'
```

#### エラーケース: 空のリクエストボディでのテスト
```bash
# 空のリクエストボディでテスト
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 5. ログ確認
```bash
# コンテナのログを確認
docker logs tweet-lambda-test

# リアルタイムでログを監視
docker logs -f tweet-lambda-test
```

### 6. データベース確認
```bash
# PostgreSQLコンテナに接続してデータを確認
docker exec -it postgres-test psql -U postgres -d birdxplorer

# テーブル一覧を確認
\dt

# データが挿入されているか確認
SELECT * FROM row_posts LIMIT 5;
SELECT * FROM row_users LIMIT 5;
SELECT * FROM row_post_media LIMIT 5;
SELECT * FROM row_post_embed_urls LIMIT 5;

# 接続を終了
\q
```

### 7. 詳細なテスト用curlコマンド

#### ヘルスチェック的なテスト
```bash
# 基本的な動作確認
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
    "tweet_id": "1234567890123456789"
  }' \
  -w "\nHTTP Status: %{http_code}\nResponse Time: %{time_total}s\n"
```

#### 詳細なレスポンス確認
```bash
# レスポンスヘッダーも含めて確認
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
    "tweet_id": "1234567890123456789"
  }' \
  -v \
  -o response.json

# レスポンスを整形して表示
cat response.json | python -m json.tool
```

#### バッチテスト用スクリプト
```bash
# 複数のテストケースを連続実行
#!/bin/bash
echo "=== Tweet Lambda Container Test ==="

# テストケース1: 正常ケース
echo "Test 1: Valid tweet ID"
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{"tweet_id": "1234567890123456789"}' \
  -w "Status: %{http_code}\n"

echo ""

# テストケース2: 無効なID
echo "Test 2: Invalid tweet ID"
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{"tweet_id": "invalid"}' \
  -w "Status: %{http_code}\n"

echo ""

# テストケース3: パラメータなし
echo "Test 3: Missing tweet_id"
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{}' \
  -w "Status: %{http_code}\n"
```

### 8. 期待される結果

#### 正常ケース (200)
```json
{
  "statusCode": 200,
  "body": "{\"tweet_id\": \"1234567890123456789\", \"data\": {...}}"
}
```

#### エラーケース - パラメータなし (400)
```json
{
  "statusCode": 400,
  "body": "{\"error\": \"Missing tweet_id in event\"}"
}
```

#### エラーケース - 処理失敗 (500)
```json
{
  "statusCode": 500,
  "body": "{\"error\": \"Lambda execution error: ...\"}"
}
```

### 9. クリーンアップ
```bash
# テスト用コンテナを停止・削除
docker stop tweet-lambda-test postgres-test
docker rm tweet-lambda-test postgres-test

# テスト用イメージを削除（必要に応じて）
docker rmi birdxplorer-tweet-lambda

# テスト用ファイルを削除
rm .env.test response.json
```

## 注意事項

1. **X API認証**: 実際のX BEARER_TOKENが必要です
2. **レート制限**: X APIのレート制限に注意してください
3. **ネットワーク**: `host.docker.internal`はDocker Desktop環境で使用可能です
4. **データベース**: PostgreSQLコンテナが起動していることを確認してください
5. **ツイートID**: テストには実際に存在するツイートIDを使用してください

## トラブルシューティング

### よくある問題と解決方法

1. **データベース接続エラー**
   - PostgreSQLコンテナが起動しているか確認
   - 環境変数の設定を確認

2. **X API認証エラー**
   - BEARER_TOKENが正しく設定されているか確認
   - トークンの有効期限を確認

3. **コンテナ起動エラー**
   - Dockerfileのビルドが成功しているか確認
   - 依存関係のインストールエラーがないか確認

4. **ポート競合**
   - ポート9000や5432が他のプロセスで使用されていないか確認