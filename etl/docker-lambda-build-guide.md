# Lambda関数用Dockerfileビルドガイド

## 概要

このガイドでは、作成したLambda関数（`language_detect_lambda.py`と`topic_detect_lambda.py`）用のDockerfileのビルドと使用方法について説明します。

## 作成されたDockerfile

### 1. Dockerfile.language_detect
- **対象**: `language_detect_lambda.py`
- **機能**: ノートの言語検出を行うLambda関数
- **ハンドラー**: `language_detect_lambda.lambda_handler`

### 2. Dockerfile.topic_detect
- **対象**: `topic_detect_lambda.py`
- **機能**: ノートのトピック推定を行うLambda関数
- **ハンドラー**: `topic_detect_lambda.lambda_handler`

## ビルド方法

### Language Detection Lambda

```bash
# etlディレクトリで実行
docker build -f Dockerfile.language_detect -t language-detect-lambda .
```

### Topic Detection Lambda

```bash
# etlディレクトリで実行
docker build -f Dockerfile.topic_detect -t topic-detect-lambda .
```

## ローカルテスト

### Language Detection Lambda

```bash
# コンテナを起動
docker run -p 9000:8080 \
  -e OPENAPI_TOKEN="your-openai-token" \
  -e CLAUDE_TOKEN="your-claude-token" \
  -e POSTGRESQL_HOST="your-db-host" \
  -e POSTGRESQL_PORT="5432" \
  -e POSTGRESQL_USER="your-db-user" \
  -e POSTGRESQL_PASSWORD="your-db-password" \
  -e POSTGRESQL_DATABASE="your-db-name" \
  language-detect-lambda
  
  or 

docker run -p 9000:8080 \
  --env-file etl/.env \
  language-detect-lambda
# テストリクエスト送信
curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"note_id": "1234567890"}'
```

### Topic Detection Lambda

```bash
# コンテナを起動
docker run -p 9001:8080 \
  -e OPENAPI_TOKEN="your-openai-token" \
  -e CLAUDE_TOKEN="your-claude-token" \
  -e POSTGRESQL_HOST="your-db-host" \
  -e POSTGRESQL_PORT="5432" \
  -e POSTGRESQL_USER="your-db-user" \
  -e POSTGRESQL_PASSWORD="your-db-password" \
  -e POSTGRESQL_DATABASE="your-db-name" \
  -e TOPIC_SOURCE="db" \
  topic-detect-lambda

or 


docker run -p 9000:8080 \
  --env-file etl/.env \
  topic-detect-lambda

# テストリクエスト送信
curl -XPOST "http://localhost:9001/2015-03-31/functions/function/invocations" \
  -d '{"note_id": "1234567890"}'
```

## 環境変数

### 共通環境変数

- `OPENAPI_TOKEN`: OpenAI APIトークン
- `CLAUDE_TOKEN`: Claude APIトークン
- `POSTGRESQL_HOST`: PostgreSQLホスト
- `POSTGRESQL_PORT`: PostgreSQLポート（デフォルト: 5432）
- `POSTGRESQL_USER`: PostgreSQLユーザー名
- `POSTGRESQL_PASSWORD`: PostgreSQLパスワード
- `POSTGRESQL_DATABASE`: PostgreSQLデータベース名

### Topic Detection Lambda専用

- `TOPIC_SOURCE`: トピック読み込み元（"csv" または "db"、デフォルト: "csv"）

## 注意事項

1. **依存関係**: 両方のLambda関数は`birdxplorer_etl`パッケージとその依存関係を必要とします
2. **データベース接続**: PostgreSQLデータベースへの接続が必要です
3. **AI APIトークン**: OpenAIまたはClaudeのAPIトークンが必要です
4. **メモリとタイムアウト**: AI API呼び出しのため、十分なメモリとタイムアウト時間を設定してください
5. **VPC設定**: データベースがVPC内にある場合、Lambda関数もVPC設定が必要です

## トラブルシューティング

### よくある問題

1. **モジュールが見つからない**: パッケージのインストールが正しく行われているか確認
2. **データベース接続エラー**: 環境変数とネットワーク設定を確認
3. **API呼び出しエラー**: APIトークンの有効性を確認
4. **タイムアウト**: Lambda関数のタイムアウト設定を増加

### ログの確認

```bash
# CloudWatch Logsでログを確認
aws logs describe-log-groups --log-group-name-prefix /aws/lambda_handler/language-detect-lambda
aws logs describe-log-groups --log-group-name-prefix /aws/lambda_handler/topic-detect-lambda