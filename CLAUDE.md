# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Architecture

BirdXplorer is a multi-module Python project for exploring X (formerly Twitter) community notes data:

- **api/**: FastAPI web API (`birdxplorer_api`)
- **common/**: Shared library with models, settings, storage (`birdxplorer_common`)
- **etl/**: Data extraction, transformation, loading (`birdxplorer_etl`)
- **migrate/**: Alembic database migrations

### Dependencies
- All modules use `birdxplorer_common` as foundation
- API and ETL modules depend on `common`
- PostgreSQL 15.4 for data storage
- FastAPI for web API with auto-generated Swagger docs at `/docs`

## Commands

### Development Environment
- **Setup env**: `cp .env.example .env` (sets `BX_STORAGE_SETTINGS__PASSWORD=birdxplorer`)
- **Install module**: `pip install -e "./[module][dev]"` (e.g., `pip install -e "./api[dev]"`)
- **Docker dev**: `docker-compose up -d` (starts PostgreSQL + FastAPI on :8000)

### Testing & Quality
- **Test all**: `tox` (from module directory - runs format, lint, test, type check)
- **Test with data**: `BX_DATA_DIR=data/20230924 tox` (for community notes data testing)
- **Run single test**: `python -m pytest path/to/test_file.py::TestClass::test_method -v`
- **Format**: `black <directory> && isort <directory>`
- **Lint**: `pflake8 <directory>`
- **Type check**: `mypy <directory> --strict`

### Database
- **Migrate**: `cd migrate && alembic upgrade head`
- **New migration**: `cd migrate && alembic revision --autogenerate -m "description"`

### Module-Specific Tox
Run from project root, then cd to module:
- **common**: `cd common && tox`
- **api**: `cd api && tox`
- **etl**: `cd etl && tox`
- **migrate**: `cd migrate && tox`

## Code Style
- **Line length**: 120 characters
- **Python version**: 3.10+
- **Formatting**: Black (opinionated)
- **Imports**: isort with Black profile, groups: standard, third-party, first-party
- **First party modules**: `birdxplorer_api`, `birdxplorer_common`, `birdxplorer_etl`
- **Type hints**: Required, use strict mypy checking
- **Naming**: Snake case for functions/variables, PascalCase for classes
- **Error handling**: Custom exceptions inherit from BaseError
- **Exception naming**: Follow pattern `<Problem>Error`
- **Testing**: Use pytest with appropriate fixtures