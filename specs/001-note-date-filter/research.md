# Research: Note Date Filter

**Feature**: 001-note-date-filter
**Date**: 2026-01-21
**Reference**: [Design Document](../../etl/docs/issue-200-date-filter-design.md)

## Research Summary

This feature has an existing design document (`etl/docs/issue-200-date-filter-design.md`) that provides detailed implementation guidance. This research consolidates and validates those decisions.

---

## Decision 1: Date Format

**Decision**: Use millisecond timestamps (existing `created_at_millis` format)

**Rationale**:
- Consistent with existing database schema (`row_notes.created_at_millis`)
- No timezone conversion issues (UTC-based)
- Direct integer comparison for filtering (performant)
- Already used throughout the codebase

**Alternatives Considered**:
- ISO 8601 strings: Rejected - would require parsing and timezone handling
- Unix seconds: Rejected - inconsistent with existing millis format

---

## Decision 2: Configuration Management

**Decision**: Create unified `settings.json` in `etl/seed/` directory

**Rationale**:
- Consolidates language, keyword, and date filters in one file
- Follows existing pattern (`keywords.json` is in same location)
- Lambda can read from `/var/task/seed/` at runtime
- Development environment uses relative path from `__file__`

**Alternatives Considered**:
- Environment variables: Rejected - complex for structured data (arrays, nested objects)
- Database configuration table: Rejected - adds complexity, seed files are simpler for static config
- Separate date-filter.json: Rejected - leads to config sprawl

**Configuration Schema**:
```json
{
  "filter": {
    "languages": ["ja", "en"],
    "keywords": [],
    "date_range": {
      "start_millis": 1704067200000
    }
  }
}
```

---

## Decision 3: Filter Order

**Decision**: Apply filters in order: Language → Keyword → Date

**Rationale**:
- Fail fast on cheapest checks first (language is a simple string comparison)
- Keyword matching is more expensive (iterates list)
- Date comparison is cheap but logically last in the chain
- Consistent with existing filter chain structure

**Alternatives Considered**:
- Date first: Rejected - no performance benefit, breaks existing log analysis patterns
- Parallel evaluation: Rejected - unnecessary complexity for sequential SQS processing

---

## Decision 4: Error Handling for Missing Configuration

**Decision**: Raise error if `start_millis` is not set (required field)

**Rationale**:
- Prevents accidental processing of all historical data
- Explicit failure is safer than implicit "process everything"
- Matches spec requirement FR-005

**Alternatives Considered**:
- Default to current date: Rejected - could miss recent notes unexpectedly
- Default to epoch (process all): Rejected - defeats purpose of the feature
- Warning + continue: Rejected - ambiguous behavior

---

## Decision 5: Backward Compatibility

**Decision**: Keep `keywords.json` during transition, load from `settings.json` as primary

**Rationale**:
- Allows gradual migration
- No breaking changes for existing deployments
- `load_keywords()` function can be deprecated but not removed immediately

**Migration Path**:
1. Phase 1: Add `settings.json`, update `note_transform_lambda.py` to use it
2. Phase 2: Mark `keywords.json` as deprecated in documentation
3. Phase 3 (future): Remove `keywords.json` and `load_keywords()` function

---

## Decision 6: Test Strategy

**Decision**: Add unit tests for new functions + integration test for filter chain

**Test Cases**:

| Function | Test Type | Cases |
|----------|-----------|-------|
| `load_settings()` | Unit | Valid file, missing file (FileNotFoundError), missing start_millis (ValueError) |
| `check_date_filter()` | Unit | Within range (True), before start (False), exact boundary (True), Decimal type conversion |
| Filter chain | Integration | All filters pass, language skip, keyword skip, date skip, logging verification |

**Rationale**:
- Follows Constitution Principle III (Test-First Discipline)
- Existing test patterns in `etl/tests/` directory
- Must pass tox (black, isort, pflake8, mypy, pytest)

---

## Technical Notes

### File Path Resolution (Lambda vs Development)

```python
# Lambda environment
lambda_task_root = os.environ.get("LAMBDA_TASK_ROOT")
if lambda_task_root:
    settings_path = Path(lambda_task_root) / "seed" / "settings.json"
else:
    # Development: relative to __file__
    settings_path = Path(__file__).parent.parent.parent.parent.parent / "seed" / "settings.json"
```

### Type Handling for `created_at_millis`

The database may return `Decimal` type for numeric fields. Always convert to `int` before comparison:

```python
created_at = int(created_at_millis)  # Handle Decimal type
```

### Logging Pattern

Follow existing pattern for skip logging:
```python
logger.info(f"Note {note_id} created_at {created_at_millis} before start_millis {start_millis}, skipping topic detection")
```

---

## Open Questions (Resolved)

| Question | Resolution |
|----------|------------|
| Need end_millis filter? | No - spec clarified only start date needed |
| What if start_millis missing? | Raise ValueError (required field) |
| Backward compatibility? | Keep keywords.json during transition |

---

## References

- [Design Document](../../etl/docs/issue-200-date-filter-design.md) - Detailed implementation design
- [LAMBDA_ARCHITECTURE.md](../../etl/src/birdxplorer_etl/lib/lambda_handler/LAMBDA_ARCHITECTURE.md) - Lambda patterns
- [note_transform_lambda.py](../../etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py) - Current implementation
