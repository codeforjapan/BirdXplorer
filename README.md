# BirdXplorer

## Description

BirdXplorer is software that helps users explore community notes data on X
(formerly known as Twitter).

## Example Usecase

See [example](./docs/example.md)

## Development

### Requirements

- [Python](https://www.python.org/) (v3.10.12)
- [PostgreSQL](https://www.postgresql.org/) (v15.4)

### Installation

```bash
pip install -e ".[dev]"
```

### Environment Vars

```bash
cp .env.example .env
```

| key                             | value       |
| ------------------------------- | ----------- |
| BX_STORAGE_SETTINGS\_\_PASSWORD | birdxplorer |

### Testing

To run basic unit tests and some integration tests, simply run the following:

```bash
tox
```

For the data model testing, you need to download community notes data and store
some directory (say `data/20230924`) and run the following:

```bash
BX_DATA_DIR=data/20230924 tox
```

### Run Server

```
$ pwd
$ your_dir/BirdXplorer
$ docker-compose up -d
```
