# BirdXplorer Development Guide

This document provides comprehensive guidance for developers who want to contribute to the BirdXplorer project.

## Project Overview

BirdXplorer is a software tool that helps users explore community notes data on X (formerly known as Twitter). The project consists of several components:

- **API**: A FastAPI-based web service that provides endpoints for querying community notes data
- **ETL**: Extract, Transform, Load processes for community notes data
- **Common**: Shared code and utilities used across the project

## Prerequisites

Before you begin development, ensure you have the following installed:

- [Python](https://www.python.org/) (v3.10.12)
- [PostgreSQL](https://www.postgresql.org/) (v15.4)
- [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) (for local development)
- [Git](https://git-scm.com/)

## Repository Structure

```
BirdXplorer/
├── api/                  # FastAPI web service
│   ├── birdxplorer_api/  # API source code
│   ├── tests/            # API tests
│   ├── Dockerfile        # Production Docker configuration
│   ├── Dockerfile.dev    # Development Docker configuration
│   └── pyproject.toml    # API package configuration
├── common/               # Shared code and utilities
│   ├── birdxplorer_common/ # Common source code
│   ├── tests/            # Common tests
│   └── pyproject.toml    # Common package configuration
├── etl/                  # Extract, Transform, Load processes
│   ├── src/              # ETL source code
│   ├── tests/            # ETL tests
│   └── pyproject.toml    # ETL package configuration
├── migrate/              # Database migration scripts
├── docs/                 # Documentation
├── scripts/              # Utility scripts
└── compose.yml           # Docker Compose configuration
```

## Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/codeforjapan/BirdXplorer.git
cd BirdXplorer
```

### 2. Set Up Environment Variables

```bash
cp .env.example .env
```

Edit the `.env` file to set the required environment variables:

```
BX_STORAGE_SETTINGS__PASSWORD=birdxplorer
```

For ETL processes, you may need additional environment variables. Check the `.env.example` file in the ETL directory:

```bash
cp etl/.env.example etl/.env
```

### 3. Development Environment Setup

#### Option 1: Using Docker Compose (Recommended)

The easiest way to get started is to use Docker Compose, which sets up all the required services:

```bash
docker compose up -d
```

This will start:
- PostgreSQL database
- API service
- Migration service

The API will be available at http://localhost:8000.

#### Option 2: Local Development Setup

If you prefer to develop without Docker, you can set up each component individually:

1. Set up a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install the project in development mode:

```bash
pip install -e ".[dev]"
```

3. Install each component:

```bash
# Install common package
cd common
pip install -e ".[dev]"
cd ..

# Install API package
cd api
pip install -e ".[dev]"
cd ..

# Install ETL package
cd etl
pip install -e ".[dev]"
cd ..
```

4. Run the API server:

```bash
cd api
uvicorn birdxplorer_api.main:app --reload
```

### 4. Database Migrations

Database migrations are managed using Alembic. To run migrations:

```bash
# Using Docker
docker compose up migrate

# Manually
cd migrate
alembic upgrade head
```

## Development Workflow

### Code Style and Linting

The project uses the following tools for code quality:

- [Black](https://black.readthedocs.io/) for code formatting
- [isort](https://pycqa.github.io/isort/) for import sorting
- [Flake8](https://flake8.pycqa.github.io/) for linting
- [MyPy](https://mypy.readthedocs.io/) for type checking

You can run all these checks using tox:

```bash
tox
```

Or run them individually:

```bash
black .
isort .
flake8
mypy
```

### Testing

The project uses pytest for testing. To run tests:

```bash
# Run all tests
tox

# Run tests for a specific component
cd api
pytest

cd ../common
pytest

cd ../etl
pytest
```

For data model testing, you need to download community notes data:

```bash
BX_DATA_DIR=data/20230924 tox
```

### API Documentation

The API documentation is available at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

### ETL Processes

The ETL processes use Prefect for workflow management. To run ETL processes:

```bash
cd etl
python -m birdxplorer_etl.main
```

## Contributing

### Pull Request Process

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

### Commit Message Guidelines

Follow the conventional commits specification:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types:
- feat: A new feature
- fix: A bug fix
- docs: Documentation changes
- style: Code style changes (formatting, etc.)
- refactor: Code changes that neither fix bugs nor add features
- perf: Performance improvements
- test: Adding or fixing tests
- chore: Changes to the build process or auxiliary tools

## Troubleshooting

### Common Issues

#### Database Connection Issues

If you encounter database connection issues, check:

1. PostgreSQL is running
2. The connection string in your `.env` file is correct
3. The database user has the necessary permissions

#### Missing Dependencies

If you encounter missing dependencies, ensure you've installed the project with the dev dependencies:

```bash
pip install -e ".[dev]"
```

#### Data Import Issues

For ETL processes, ensure you have the correct data directory set:

```bash
export BX_DATA_DIR=path/to/data
```

## Additional Resources

- [Example Use Cases](./example.md)
- [API Documentation](https://birdxplorer.onrender.com/docs)
- [OpenAPI Specification](https://birdxplorer.onrender.com/openapi.json)
