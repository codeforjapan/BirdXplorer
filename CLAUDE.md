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

## Development Workflow (CRITICAL - Follow This Exactly)

### Test-First Discipline (Constitution Principle III)
**NEVER skip writing tests. NEVER mark test tasks complete without actually running them.**

1. **Write tests FIRST** before implementation
   - Common module tests: `common/tests/test_storage_graphs.py` (for new storage methods)
   - API module tests: `api/tests/routers/test_graphs.py` (for new endpoints)
   - Tests should FAIL initially (red phase)

2. **Implement the feature** to make tests pass (green phase)

3. **Run tox in BOTH modules** (DO NOT skip this step):
   ```bash
   cd common && tox  # Must show "congratulations :)"
   cd api && tox     # Must show "congratulations :)"
   ```

4. **Fix ALL issues** found by tox before proceeding:
   - Doctest failures: Fix examples in docstrings
   - E501 line length: Break long lines at 120 chars
   - F401 unused imports: Remove them
   - Type errors: Add proper type hints (e.g., `Generic[T]`, `dict[str, Union[str, int]]`)

### Updating Test Mocks
When adding new storage methods, **you MUST update** `api/tests/conftest.py`:
```python
# In mock_storage fixture, add side_effect for new methods:
def _new_method(...) -> ...:
    # Mock implementation
    return ...

mock.new_method.side_effect = _new_method
```

### Tox Quality Gates (All Must Pass)
- ✅ **black**: Code formatting
- ✅ **isort**: Import sorting
- ✅ **pytest**: All tests pass with coverage
- ✅ **pflake8**: Linting (0 errors)
- ✅ **mypy --strict**: Type checking (0 errors)

### Commit Strategy
Follow these commit patterns:
1. **Foundation**: Infrastructure/setup (migrations, models, helpers)
2. **Implementation**: Feature code (endpoints, storage methods)
3. **Tests**: Test files and quality fixes
4. Use conventional commit format: `feat:`, `test:`, `fix:`, `docs:`

### Common Issues and Solutions

**Issue**: Doctest failures
```python
# ❌ Bad: Exact dict comparison fails
>>> func()
{"key": "value"}

# ✅ Good: Test structure, not exact format
>>> result = func()
>>> len(result)
3
>>> result[0]["key"]
'value'
```

**Issue**: MyPy type errors with SQLAlchemy
```python
# ✅ Solution: Use Any for CASE expressions
def _get_case_expr(cls) -> Any:  # Not -> case
    return case(...)
```

**Issue**: Test mocks return MagicMock instead of values
```python
# ✅ Solution: Add side_effect in conftest.py
mock.get_graph_updated_at.side_effect = lambda table: "2025-01-15"
```

### Spec-Driven Development
- **Source of truth**: `specs/*/tasks.md` file
- Mark tasks with `[X]` only after ACTUALLY completing them
- Follow phase order: Setup → Tests → Implementation → Polish
- Update tasks.md in each commit to track progress

### File Organization
```
common/
  birdxplorer_common/
    models.py          # Pydantic models, enums
    storage.py         # Database methods
  tests/
    test_storage_graphs.py  # Storage method tests

api/
  birdxplorer_api/
    routers/
      graphs.py        # FastAPI endpoints
  tests/
    conftest.py        # Test fixtures and mocks
    routers/
      test_graphs.py   # Endpoint tests
```

## Active Technologies
- Python 3.10.12+ (existing project standard) + FastAPI, SQLAlchemy 2.x, Pydantic (existing stack) (001-graph-api-backend)
- PostgreSQL 15.4+ with existing `notes` and `posts` tables (001-graph-api-backend)
- Python 3.10+ + SQLAlchemy, birdxplorer_common, boto3 (SQS) (001-note-date-filter)
- PostgreSQL 15.4+ (row_notes, notes tables) (001-note-date-filter)

## Recent Changes
- 001-graph-api-backend: Added Python 3.10.12+ (existing project standard) + FastAPI, SQLAlchemy 2.x, Pydantic (existing stack)
