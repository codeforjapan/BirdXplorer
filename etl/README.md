# BirdXplorer ETL

This is an ETL to get and process data of community notes and X posts, in order to prepare API.

## Setup development environment

### Set setting variables

```
$ cp .env.example .env
```

| Key            | Description             |
| -------------- | ----------------------- |
| X_BEARER_TOKEN | API key for Twitter API |

### Run

日次バッチ(ECS タスク)をローカルで動かす場合:

```
$ pwd
/your_dir/BirdXplorer/etl
$ pip install .
$ python src/birdxplorer_etl/run_extract.py
```

SQS 連携を含む Lambda 群をまとめて動かす場合は、リポジトリルートの
`compose-etl.yml` を使う(詳細は `docs/etl-local-testing-guide.md`)。

```
$ docker compose -f compose-etl.yml up -d
```
