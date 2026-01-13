# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands
- **Test**: `tox` (runs format, lint, test, type check)
- **Run single test**: `python -m pytest path/to/test_file.py::TestClass::test_method -v`
- **Format**: `black <directory> && isort <directory>`
- **Lint**: `pflake8 <directory>`
- **Type check**: `mypy <directory> --strict`

## Code Style
- **Line length**: 120 characters
- **Python version**: 3.10+
- **Formatting**: Black (opinionated)
- **Imports**: isort with Black profile, groups: standard, third-party, first-party
- **Type hints**: Required, use strict mypy checking
- **Naming**: Snake case for functions/variables, PascalCase for classes
- **Error handling**: Custom exceptions inherit from BaseError
- **Exception naming**: Follow pattern `<Problem>Error`
- **Testing**: Use pytest with appropriate fixtures

## Active Technologies
- Python 3.10.12+ (existing project standard) + FastAPI, SQLAlchemy 2.x, Pydantic (existing stack) (001-graph-api-backend)
- PostgreSQL 15.4+ with existing `notes` and `posts` tables (001-graph-api-backend)

## Recent Changes
- 001-graph-api-backend: Added Python 3.10.12+ (existing project standard) + FastAPI, SQLAlchemy 2.x, Pydantic (existing stack)
