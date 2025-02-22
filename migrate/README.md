
# BirdXplorer Migrations

## Alembic によるマイグレーション

### 前提条件

- `birdxplorer_common` のインストールが完了していること
- `birdxplorer_migration` のインストールが完了していること
- `.env` ファイルに `BX_STORAGE_SETTINGS__PASSWORD` が設定されていること
  - DB のデフォルトホスト名 `db` が解決できない場合は `BX_STORAGE_SETTINGS__HOST` も設定すること

### 現在のマイグレーションを適用する

データベースのスキーマを最新の状態にします。

`alembic.ini` があるディレクトリの場合:

```bash
alembic upgrade head
```

`alembic.ini` が別の場所にある場合:

```bash
alembic upgrade head -c /path/to/alembic.ini
```

### 新しいマイグレーションを作成する

データベースのスキーマを変更した場合、以下の手順で新しいマイグレーションを作成します。

`alembic.ini` があるディレクトリの場合:

```bash
alembic revision --autogenerate -m "マイグレーションの説明"
```

`alembic.ini` が別の場所にある場合:

```bash
alembic revision --autogenerate -m "マイグレーションの説明" -c /path/to/alembic.ini
```

