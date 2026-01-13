<!--
Sync Impact Report:
Version Change: None → 1.0.0
Modified Principles: N/A (Initial ratification)
Added Sections:
  - Core Principles (I-VII)
  - Technology Standards
  - Development Workflow
  - Governance
Templates Status:
  ✅ plan-template.md - Constitution Check section aligns with principles
  ✅ spec-template.md - User story requirements align with testing principles
  ✅ tasks-template.md - Task structure aligns with modular architecture and testing discipline
Follow-up TODOs: None
-->

# BirdXplorer Constitution

## Core Principles

### I. Modular Architecture

The project MUST maintain a clear separation of concerns across four distinct modules:

- **common**: Shared library containing data models, database interfaces, settings, and utilities. This module MUST be independently testable and usable by other modules.
- **api**: Web API service exposing BirdXplorer functionality via REST endpoints. MUST depend only on common.
- **etl**: Extract-Transform-Load pipeline for ingesting and processing X (Twitter) community notes data. MUST depend only on common.
- **migrate**: Database migration scripts using Alembic. MUST depend only on common.

**Rationale**: This modular structure enables independent development, testing, and deployment of each component. The common module provides a stable foundation that prevents duplication and ensures consistency across services.

### II. Database-Centric Design

All modules MUST use PostgreSQL 15.4+ as the single source of truth for data persistence. Data models MUST be defined in the common module using SQLAlchemy ORM with strict type annotations.

**Rationale**: Centralized data management in PostgreSQL ensures consistency, enables complex queries, supports concurrent access, and provides ACID guarantees essential for community notes data integrity.

### III. Test-First Discipline (NON-NEGOTIABLE)

Every module MUST maintain comprehensive test coverage through tox. Tests MUST include:

- **Format checks**: Black (120 char line length) and isort (Black profile)
- **Linting**: pyproject-flake8 with strict rules
- **Type checking**: mypy with --strict flag
- **Unit and integration tests**: pytest with appropriate fixtures

The common module additionally requires database integration tests with PostgreSQL service.

**Rationale**: Automated quality gates prevent regression, enforce code consistency, and ensure type safety across the entire Python 3.10+ codebase. The strict mypy requirement catches type errors before runtime.

### IV. Dependency Management

- Each module MUST declare dependencies explicitly in pyproject.toml
- The common module MUST NOT depend on api, etl, or migrate
- Production deployments MUST use git references for cross-module dependencies
- Development environments MUST use local editable installs (pip install -e)

**Rationale**: Explicit dependency graphs prevent circular dependencies and enable independent versioning. Git-based production dependencies ensure reproducible builds while local development dependencies enable rapid iteration.

### V. Environment Configuration

All modules MUST use .env files for configuration. The .env.example file at repository root provides the template. Sensitive credentials (database passwords, API keys) MUST be externalized and MUST NOT be committed to version control.

**Rationale**: Environment-based configuration enables deployment portability, protects secrets, and supports multiple environments (development, staging, production) without code changes.

### VI. Structured Testing Gates

Tests MUST be executed through tox for consistency. Each module MUST pass all four quality gates (format, lint, type check, tests) before code review. The CI workflow (.github/workflows/test.yml) MUST enforce these gates on all pull requests.

**Rationale**: Consistent quality enforcement prevents technical debt accumulation. Automated CI checks ensure no untested or poorly formatted code reaches the main branch.

### VII. Python Standards

All code MUST adhere to:

- Python 3.10+ language features and typing
- Black formatting (120 character line length)
- isort import sorting with Black profile and first-party package awareness
- Snake case for functions/variables, PascalCase for classes
- Custom exceptions inheriting from BaseError with `<Problem>Error` naming pattern
- Strict mypy type checking

**Rationale**: Consistent code style reduces cognitive load, improves maintainability, and enables better tooling support. Strict typing prevents entire classes of runtime errors.

## Technology Standards

### Language and Runtime

- **Python Version**: 3.10.12+ (consistent across all modules)
- **Build System**: flit_core 3.8.0+ (api, common, migrate) or setuptools (etl)
- **Package Management**: pip with editable installs for development

### Core Dependencies

- **API Framework**: FastAPI with Uvicorn (standard configuration)
- **ORM**: SQLAlchemy with Pydantic integration
- **Database Driver**: psycopg2 (production), psycopg2-binary (development)
- **Settings Management**: pydantic_settings with python-dotenv
- **ETL Framework**: Prefect for workflow orchestration
- **Data Processing**: pandas for tabular data operations
- **External APIs**: twscrape for X (Twitter) data access

### Testing Stack

- **Test Framework**: pytest with pytest-cov for coverage
- **Mocking**: pytest-mock and polyfactory for test data generation
- **Time Mocking**: freezegun for deterministic time-based tests
- **Format**: Black (line-length=120, target-version=py310)
- **Lint**: pyproject-flake8 (max-line-length=120, extend-ignore=E203,E701)
- **Type Check**: mypy (python_version=3.10, strict mode, Pydantic plugin)
- **Import Sort**: isort (profile=black, known_first_party includes all birdxplorer modules)

## Development Workflow

### Local Development

1. Clone repository and navigate to desired module directory
2. Copy .env.example to .env and configure environment variables
3. Install dependencies: `pip install -e ".[dev]"`
4. For modules depending on common: `pip install -e ../common`
5. Run full test suite: `tox`

### Module-Specific Commands

- **Run single test**: `python -m pytest path/to/test_file.py::TestClass::test_method -v`
- **Format code**: `black <directory> && isort <directory>`
- **Lint code**: `pflake8 <directory>`
- **Type check**: `mypy <directory> --strict`

### Database Operations

The common module tests require PostgreSQL service:

```yaml
services:
  postgres:
    image: postgres:15.4
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: birdxplorer
      POSTGRES_DB: postgres
    ports:
      - 5432:5432
```

### Continuous Integration

GitHub Actions workflow (.github/workflows/test.yml) MUST run on workflow_call trigger:

- **common-test-check**: Tests with PostgreSQL service, 5-minute timeout
- **api-test-check**: Tests without external services, 5-minute timeout
- **etl-test-check**: Tests with X credentials (from secrets), 5-minute timeout

Each job MUST:
1. Checkout code (actions/checkout@v4)
2. Setup Python 3.10 (actions/setup-python@v4) with pip cache
3. Install dev dependencies
4. Copy .env.example to module .env
5. Run tox (etl uses pytest directly due to async requirements)

### Code Review Requirements

All pull requests MUST:
- Pass all CI checks (format, lint, type, tests)
- Include tests for new functionality
- Update .env.example if new configuration is added
- Follow module dependency constraints
- Maintain or improve test coverage

### Documentation Standards

- **README.md**: High-level project overview and development setup
- **CLAUDE.md**: AI agent guidance for code standards and commands
- **docs/**: May contain supplementary documentation (currently outdated, use caution)
- **Module READMEs**: Each module should document its specific purpose and usage

## Governance

This constitution supersedes all other development practices. All code changes, architectural decisions, and tooling selections MUST comply with these principles.

### Amendment Procedure

1. Propose amendment with justification in GitHub issue or pull request
2. Document backward compatibility impact
3. Update affected templates (.specify/templates/*.md)
4. Increment version according to semantic versioning:
   - **MAJOR**: Backward incompatible governance or principle removal/redefinition
   - **MINOR**: New principle added or materially expanded guidance
   - **PATCH**: Clarifications, wording improvements, non-semantic refinements
5. Update LAST_AMENDED_DATE to date of merge
6. Require approval from project maintainers before merge

### Compliance Review

- All pull requests MUST verify compliance with constitution principles
- Violations MUST be justified in the Complexity Tracking section of plan.md
- Unjustified complexity additions MUST be rejected
- Regular audits SHOULD be conducted to ensure ongoing compliance

### Guidance References

- **CLAUDE.md**: Provides agent-specific development guidance and command references
- **.specify/templates/**: Contains templates for feature specification, planning, and task management that implement these principles

**Version**: 1.0.0 | **Ratified**: 2026-01-13 | **Last Amended**: 2026-01-13
