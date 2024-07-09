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

```
$ pwd
/your_dir/BirdXplorer/etl
$ pip install .
$ python src/birdxplorer_etl/main.py
```
