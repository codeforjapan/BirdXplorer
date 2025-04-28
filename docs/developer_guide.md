# BirdXplorerの新規開発者向けドキュメント

このドキュメントは、BirdXplorerプロジェクトの新規開発者向けに、開発環境のセットアップから基本的な操作方法までを解説します。

## 目次

1. [toxコマンドでテスト環境を構築する](#1-toxコマンドでテスト環境を構築する)
2. [Dockerで開発環境を立ち上げる](#2-dockerで開発環境を立ち上げる)
3. [DBマイグレーションを実行する](#3-dbマイグレーションを実行する)
4. [SwaggerでAPIスペックを確認する](#4-swaggerでapiスペックを確認する)

## 1. toxコマンドでテスト環境を構築する

BirdXplorerは複数のPythonモジュール（api, common, migrate）で構成されています。各モジュールは独自のpyproject.tomlファイルを持ち、toxを使用してテスト環境を構築できます。

### 前提条件

- Python 3.10.12以上がインストールされていること
- pipがインストールされていること

### 手順

1. リポジトリをクローンする

```bash
git clone https://github.com/codeforjapan/BirdXplorer.git
cd BirdXplorer
```

2. 環境変数ファイルを作成する

```bash
cp .env.example .env
```

3. 各モジュールの開発依存関係をインストールする

```bash
# commonモジュールをインストール
pip install -e "./common[dev]"

# apiモジュールをインストール
pip install -e "./api[dev]"
```

4. toxを使用してテストを実行する

各モジュールのテストは、プロジェクトのルートディレクトリから以下のように実行します：

```bash
# commonモジュールのテスト
cd common
tox

# apiモジュールのテスト
cd api
tox
```

toxは以下の処理を自動的に実行します：

- black: コードフォーマット
- isort: importの整理
- pytest: ユニットテスト
- pflake8: コードリント
- mypy: 型チェック

コミュニティノートのデータを使用したテストを実行する場合は、以下のように環境変数を設定します：

```bash
BX_DATA_DIR=data/20230924 tox
```

## 2. Dockerで開発環境を立ち上げる

BirdXplorerはDockerを使用して開発環境を簡単に構築できます。

### 前提条件

- Docker Engineがインストールされていること
- Docker Composeがインストールされていること

### 手順

1. 環境変数ファイルを作成する（まだ作成していない場合）

```bash
cp .env.example .env
```

2. Docker Composeで開発環境を起動する

```bash
docker-compose -f compose.yml up -d
```

これにより、以下のサービスが起動します：

- **db**: PostgreSQL 15.4データベース（ポート5432）
- **app**: FastAPIアプリケーション（ポート8000）

3. サービスの状態を確認する

```bash
docker-compose -f compose.yml ps
```

4. ログを確認する

```bash
docker-compose -f compose.yml logs -f
```

5. 開発環境を停止する

```bash
docker-compose -f compose.yml down
```

データベースのデータを完全に削除する場合は、ボリュームも削除します：

```bash
docker-compose -f compose.yml down -v
```

## 3. DBマイグレーションを実行する

BirdXplorerはAlembicを使用してデータベースマイグレーションを管理しています。

### 前提条件

- `birdxplorer_common`がインストールされていること
- `migrate`モジュールがインストールされていること
- `.env`ファイルに`BX_STORAGE_SETTINGS__PASSWORD`が設定されていること

### 手順

1. migrateディレクトリに移動する

```bash
cd migrate
```

2. 最新のマイグレーションを適用する

```bash
alembic upgrade head
```

3. 新しいマイグレーションを作成する（スキーマ変更時）

```bash
alembic revision --autogenerate -m "マイグレーションの説明"
```

4. 特定のバージョンにマイグレーションする

```bash
# 特定のリビジョンIDにマイグレーション
alembic upgrade <revision_id>

# 1つ前のバージョンに戻す
alembic downgrade -1
```

5. マイグレーション履歴を確認する

```bash
alembic history
```

## 4. SwaggerでAPIスペックを確認する

BirdXplorerはFastAPIを使用しており、自動生成されたSwagger UIでAPIスペックを確認できます。

### 前提条件

- 開発環境が起動していること（Docker Composeまたはローカル環境）

### 手順

1. 開発環境を起動する

```bash
docker-compose -f compose.yml up -d
```

2. ブラウザでSwagger UIにアクセスする

開発環境が起動したら、ブラウザで以下のパスにアクセスします：

```
/docs
```

FastAPIは標準で`/docs`パスにSwagger UIを提供します。開発環境のホストとポートに応じてアクセスしてください。

3. APIエンドポイントの詳細を確認する

Swagger UIでは以下の情報を確認できます：

- 利用可能なすべてのAPIエンドポイント
- 各エンドポイントのリクエストパラメータとレスポンス形式
- リクエストの例とレスポンスの例
- APIを直接テストする機能

主要なエンドポイント：

- `/api/v1/data/posts`: Postデータを取得
- `/api/v1/data/notes`: コミュニティノートデータを取得
- `/api/v1/data/topics`: トピックデータを取得
- `/api/v1/data/search`: 検索機能

各エンドポイントの詳細なパラメータや使用例はSwagger UIで確認できます。

---

このドキュメントがBirdXplorerの開発環境セットアップと基本的な操作の理解に役立つことを願っています。さらに詳細な情報は、各モジュールのREADMEファイルやソースコードのコメントを参照してください。
