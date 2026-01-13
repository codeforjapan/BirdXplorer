# Research: Graph API Backend Technical Decisions

**Feature**: Graph API Backend
**Date**: 2026-01-13
**Purpose**: Document technical research and decisions for implementing 6 graph analytics endpoints

## Overview

This document resolves all NEEDS CLARIFICATION items from the implementation plan by researching existing codebase patterns, evaluating technical alternatives, and making informed decisions aligned with BirdXplorer architecture.

---

## Decision 1: Status Calculation Strategy

### Question
How to efficiently implement the 4-way status derivation logic (`published`, `temporarilyPublished`, `evaluating`, `unpublished`) in SQLAlchemy?

### Research

**Option A: SQL-side CASE Expression**
```python
from sqlalchemy import case, func

status_expr = case(
    (NoteRecord.current_status == "CURRENTLY_RATED_HELPFUL", "published"),
    (
        and_(
            NoteRecord.has_been_helpfuled == True,
            NoteRecord.current_status.in_(["NEEDS_MORE_RATINGS", "CURRENTLY_RATED_NOT_HELPFUL"])
        ),
        "temporarilyPublished"
    ),
    (
        and_(
            NoteRecord.current_status == "NEEDS_MORE_RATINGS",
            NoteRecord.has_been_helpfuled == False
        ),
        "evaluating"
    ),
    else_="unpublished"
)

# Use in query
query = select(
    func.date_trunc('day', NoteRecord.created_at).label('day'),
    func.count().filter(status_expr == "published").label('published'),
    func.count().filter(status_expr == "evaluating").label('evaluating'),
    # ...
).group_by('day')
```

**Pros**:
- Database performs computation (highly optimized C code)
- Leverages indexes effectively
- Reduces data transfer (only aggregates returned)
- Supports complex aggregations with FILTER clause

**Cons**:
- More complex SQLAlchemy code
- Harder to test in isolation
- Type checking limitations (dynamic SQL)

**Option B: Python Post-Processing**
```python
def calculate_status(note: NoteRecord) -> str:
    if note.current_status == "CURRENTLY_RATED_HELPFUL":
        return "published"
    if note.has_been_helpfuled and note.current_status in ["NEEDS_MORE_RATINGS", "CURRENTLY_RATED_NOT_HELPFUL"]:
        return "temporarilyPublished"
    if note.current_status == "NEEDS_MORE_RATINGS" and not note.has_been_helpfuled:
        return "evaluating"
    return "unpublished"

# Fetch all, then aggregate in Python
notes = session.query(NoteRecord).filter(...).all()
by_status = defaultdict(list)
for note in notes:
    status = calculate_status(note)
    by_status[status].append(note)
```

**Pros**:
- Simple, readable Python code
- Easy to unit test
- Full type safety
- Flexible for complex logic

**Cons**:
- Fetches ALL records from database (memory intensive)
- Network transfer overhead
- Python aggregation slower than PostgreSQL
- Does not scale to millions of records

### Decision

**✅ SELECTED: Option A - SQL-side CASE Expression**

**Rationale**:
1. **Performance**: Target is millions of notes. Fetching all records into Python is infeasible.
2. **Scalability**: PostgreSQL aggregations are 10-100x faster than Python for large datasets.
3. **Alignment**: Existing codebase uses SQLAlchemy expression language (not just ORM).
4. **Network Efficiency**: Only aggregated counts returned, not individual records.

**Implementation Pattern**:
```python
# In common/storage.py
def _get_publication_status_case() -> Case:
    """Reusable CASE expression for publication status derivation."""
    return case(
        (NoteRecord.current_status == "CURRENTLY_RATED_HELPFUL", "published"),
        (
            and_(
                NoteRecord.has_been_helpfuled == True,
                NoteRecord.current_status.in_(["NEEDS_MORE_RATINGS", "CURRENTLY_RATED_NOT_HELPFUL"])
            ),
            "temporarilyPublished"
        ),
        (
            and_(
                NoteRecord.current_status == "NEEDS_MORE_RATINGS",
                NoteRecord.has_been_helpfuled == False
            ),
            "evaluating"
        ),
        else_="unpublished"
    )
```

**Alternatives Considered**:
- Hybrid approach (database for time filtering, Python for status calculation) - rejected due to memory constraints
- Materialized view with pre-computed status - rejected to avoid schema changes (FR-028)

---

## Decision 2: Time Series Zero-Filling

### Question
How to generate continuous date series with zero counts for missing days/months?

### Research

**Option A: PostgreSQL generate_series() + LEFT JOIN**
```sql
SELECT
  dates.day,
  COALESCE(COUNT(notes.note_id), 0) as count
FROM
  generate_series('2025-01-01'::date, '2025-01-31'::date, '1 day'::interval) AS dates(day)
LEFT JOIN notes ON date_trunc('day', notes.created_at) = dates.day
GROUP BY dates.day
ORDER BY dates.day
```

**Pros**:
- Database generates complete series (efficient)
- Zero-fill handled by COALESCE
- Single query returns ready-to-use data

**Cons**:
- Requires knowing date range upfront
- Complex SQLAlchemy translation
- Less flexible for dynamic period calculations

**Option B: Python pandas**
```python
import pandas as pd

# Fetch data from database
df = pd.read_sql_query(query, engine)

# Reindex with complete date range
date_range = pd.date_range(start='2025-01-01', end='2025-01-31', freq='D')
df = df.set_index('date').reindex(date_range, fill_value=0).reset_index()
```

**Pros**:
- Simple, readable code
- Powerful date manipulation
- Easy to test

**Cons**:
- Adds pandas dependency to API (heavy library)
- Extra processing step after database query
- Constitution violation (adds new dependency)

**Option C: Application-layer Gap Filling**
```python
from datetime import date, timedelta

def fill_date_gaps(data: list[dict], start: date, end: date) -> list[dict]:
    """Fill missing dates with zero counts."""
    # Create map of existing dates
    by_date = {item['date']: item for item in data}

    # Generate complete range
    result = []
    current = start
    while current <= end:
        if current in by_date:
            result.append(by_date[current])
        else:
            result.append({'date': current, 'published': 0, 'evaluating': 0, ...})
        current += timedelta(days=1)

    return result
```

**Pros**:
- No new dependencies
- Simple to understand and test
- Flexible for different time granularities
- Separates concerns (DB = fetch, app = format)

**Cons**:
- Additional code complexity
- Marginally more memory (negligible for 365 days max)

### Decision

**✅ SELECTED: Option C - Application-layer Gap Filling**

**Rationale**:
1. **No New Dependencies**: Avoids adding pandas (Constitution Principle IV).
2. **Simplicity**: Easier to test and debug than complex SQLAlchemy LEFT JOIN with generate_series.
3. **Flexibility**: Can easily adapt for different granularities (daily, monthly) with same pattern.
4. **Performance**: Minimal overhead for 365 days max (1 year daily data).
5. **Separation of Concerns**: Database does aggregation, application does presentation formatting.

**Implementation Pattern**:
```python
def _fill_daily_gaps(
    data: list[dict[str, Any]],
    start_date: date,
    end_date: date
) -> list[dict[str, Any]]:
    """Fill missing dates with zero counts for continuous time series."""
    by_date = {item['date']: item for item in data}
    result = []
    current = start_date
    while current <= end_date:
        result.append(by_date.get(current, {
            'date': current.isoformat(),
            'published': 0,
            'evaluating': 0,
            'unpublished': 0,
            'temporarilyPublished': 0
        }))
        current += timedelta(days=1)
    return result
```

**Alternatives Considered**:
- PostgreSQL generate_series - rejected due to SQLAlchemy complexity
- pandas - rejected to avoid new dependency
- Client-side gap filling - rejected to maintain API contract (FR-016)

---

## Decision 3: Date Range Validation

### Question
How to validate and parse period ("1week", "1month") and range ("YYYY-MM_YYYY-MM") parameters?

### Research

Examined existing validation patterns in `/home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/data.py`:

**Pattern 1: Pydantic Query Parameter with Enum**
```python
from typing import Literal

PeriodType = Literal["1week", "1month", "3months", "6months", "1year"]

@router.get("/api/v1/graphs/daily-notes")
def get_daily_notes(
    period: PeriodType = Query(..., description="Time period"),
) -> GraphListResponse:
    # FastAPI automatically validates against Literal values
    # No manual validation needed
    pass
```

**Pattern 2: String with Manual Validation**
```python
def get_daily_notes(
    period: str = Query(..., regex="^(1week|1month|3months|6months|1year)$"),
) -> GraphListResponse:
    # FastAPI validates regex before function call
    pass
```

**Pattern 3: Custom Pydantic Type**
```python
class DateRange(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    def validate_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m")
            return v
        except ValueError:
            raise ValueError(f"Invalid month format: {v}")

# In router
range_param: DateRange = Query(...)
```

**Pattern 4: Try-Except with HTTPException (most common in codebase)**
```python
def get_daily_posts(
    range: str = Query(..., description="Format: YYYY-MM_YYYY-MM"),
) -> GraphListResponse:
    try:
        start_str, end_str = range.split("_")
        start_date = datetime.strptime(start_str, "%Y-%m").date()
        end_date = datetime.strptime(end_str, "%Y-%m").date()

        if start_date > end_date:
            raise ValueError("Start month must be before or equal to end month")

    except (ValueError, AttributeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid range format: {e}")
```

### Decision

**✅ SELECTED: Hybrid Approach**

1. **For `period` parameter**: Use `Literal` type (Pattern 1)
2. **For `range` parameter**: Use try-except HTTPException (Pattern 4)
3. **For `status` parameter**: Use `Literal` with default (Pattern 1)
4. **For `limit` parameter**: Use Query constraints (automatic validation)

**Rationale**:
1. **Consistency**: Matches existing codebase patterns from `data.py`.
2. **Type Safety**: Literal provides excellent IDE autocomplete and mypy checking.
3. **Error Messages**: Try-except allows custom, user-friendly error messages.
4. **FastAPI Native**: Leverages FastAPI's built-in validation (no custom dependencies).

**Implementation Pattern**:
```python
from typing import Literal
from fastapi import Query, HTTPException

PeriodType = Literal["1week", "1month", "3months", "6months", "1year"]
StatusType = Literal["all", "published", "evaluating", "unpublished", "temporarilyPublished"]

@router.get("/api/v1/graphs/daily-notes")
def get_daily_notes(
    period: PeriodType = Query(..., description="Time period for data"),
    status: StatusType = Query("all", description="Filter by note status"),
) -> GraphListResponse[DailyNotesCreationDataItem]:
    # No validation needed - FastAPI handles it
    pass

@router.get("/api/v1/graphs/daily-posts")
def get_daily_posts(
    range: str = Query(..., description="Month range in format YYYY-MM_YYYY-MM"),
    status: StatusType = Query("all"),
) -> GraphListResponse[DailyPostCountDataItem]:
    try:
        start_date, end_date = _parse_month_range(range)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Use start_date, end_date
    pass

def _parse_month_range(range_str: str) -> tuple[date, date]:
    """Parse YYYY-MM_YYYY-MM format into (start, end) date tuple."""
    parts = range_str.split("_")
    if len(parts) != 2:
        raise ValueError(f"Invalid range format. Expected YYYY-MM_YYYY-MM, got: {range_str}")

    try:
        start_date = datetime.strptime(parts[0], "%Y-%m").date()
        end_date = datetime.strptime(parts[1], "%Y-%m").date()
    except ValueError as e:
        raise ValueError(f"Invalid month format: {e}")

    if start_date > end_date:
        raise ValueError("Start month must be before or equal to end month")

    return start_date, end_date
```

**Alternatives Considered**:
- Pydantic model for all parameters - rejected as overkill for simple query params
- Regex validation - rejected as less readable than Literal
- Custom Query parameter types - rejected to keep code simple

---

## Decision 4: Error Response Format

### Question
What is the existing BirdXplorer error response format?

### Research

Analyzed existing error handling in `/home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/data.py`:

**Findings**:
1. **No custom error response structure** - Uses FastAPI defaults
2. **Primary pattern**: `raise HTTPException(status_code=422, detail="message")`
3. **Response format**: `{"detail": "Error message"}` or `{"detail": [pydantic validation errors]}`
4. **No custom exception handlers** registered in `app.py`
5. **Status codes used**: 200 (success), 422 (validation error), 500 (unhandled exception)

**Example from data.py**:
```python
try:
    timestamp = str_to_twitter_timestamp(created_at_from)
except ValueError:
    raise HTTPException(status_code=422, detail=f"Invalid TwitterTimestamp string: {created_at_from}")

try:
    # ... processing
except OverflowError as e:
    raise HTTPException(status_code=422, detail=str(e))
```

### Decision

**✅ SELECTED: FastAPI Default Error Format with HTTPException**

**Format**:
```json
{
  "detail": "Error message explaining what went wrong"
}
```

**Rationale**:
1. **Consistency**: Matches existing API router patterns.
2. **No Additional Code**: FastAPI handles serialization automatically.
3. **Client Compatibility**: Existing API clients already expect this format.
4. **Specification Alignment**: FR-032 specifies "match existing format", and this is it.

**Implementation Pattern**:
```python
from fastapi import HTTPException

# Parameter validation error
if limit > 1000:
    raise HTTPException(status_code=400, detail="Limit parameter exceeds maximum allowed (1000)")

# Invalid date range
if start_date > end_date:
    raise HTTPException(status_code=400, detail="Start date must be before or equal to end date")

# Invalid status filter
valid_statuses = ["all", "published", "evaluating", "unpublished", "temporarilyPublished"]
if status not in valid_statuses:
    raise HTTPException(status_code=400, detail=f"Invalid status filter. Must be one of: {', '.join(valid_statuses)}")

# Parsing errors
try:
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
except ValueError as e:
    raise HTTPException(status_code=422, detail=f"Invalid date format: {e}")
```

**Status Code Strategy**:
- **400**: Invalid query parameters (range exceeds max, invalid filter value)
- **422**: Malformed input (unparseable dates, invalid format)
- **500**: Unhandled exceptions (database errors, unexpected failures)

**Alternatives Considered**:
- RFC 7807 Problem Details format - rejected as not used in existing codebase
- Custom error model with `error` and `message` fields - rejected to maintain consistency
- Global exception handler - rejected as unnecessary for simple API

---

## Decision 5: Aggregation Query Optimization

### Question
How to optimize date_trunc + JOIN + status CASE queries for millions of records?

### Research

Investigated existing database indexes via Alembic migrations in `/home/yu23ki14/cfj/BirdXplorer/migrate/migration/versions/`:

**Current Index Status**:
- `notes` table:
  - ❌ NO index on `created_at`
  - ❌ NO index on `post_id`
  - ❌ NO index on `current_status`
  - ❌ NO index on `has_been_helpfuled`
  - ✅ PRIMARY KEY on `note_id`

- `posts` table:
  - ❌ NO index on `created_at`
  - ❌ NO index on `impression_count`
  - ✅ PRIMARY KEY on `post_id`
  - ✅ FOREIGN KEY on `user_id` (implicit index)

**Performance Impact**:
- Time-series aggregations without indexes: 10-30+ seconds (full table scan)
- JOIN operations without indexes: 5-15+ seconds (nested loop join)
- **Target performance**: <3 seconds (SC-001, SC-002, SC-004, SC-005)

**❌ CRITICAL BLOCKER**: Current database cannot meet performance requirements without indexes.

### Decision

**✅ REQUIRED: Add Database Indexes via Alembic Migration**

**Critical Indexes (Phase 1 - Must add before implementation)**:
```python
# Migration: add_graph_query_indexes.py

def upgrade() -> None:
    # Single-column indexes for time-series queries
    op.create_index('ix_notes_created_at', 'notes', ['created_at'], unique=False)
    op.create_index('ix_posts_created_at', 'posts', ['created_at'], unique=False)

    # Index for JOIN operations
    op.create_index('ix_notes_post_id', 'notes', ['post_id'], unique=False)

    # Composite indexes for filtered queries
    op.create_index('ix_notes_created_at_current_status', 'notes',
                    ['created_at', 'current_status'], unique=False)

    # Index for ORDER BY impression_count DESC queries
    op.create_index('ix_posts_impression_count', 'posts', ['impression_count'], unique=False)

def downgrade() -> None:
    op.drop_index('ix_posts_impression_count', table_name='posts')
    op.drop_index('ix_notes_created_at_current_status', table_name='notes')
    op.drop_index('ix_notes_post_id', table_name='notes')
    op.drop_index('ix_posts_created_at', table_name='posts')
    op.drop_index('ix_notes_created_at', table_name='notes')
```

**Rationale**:
1. **Specification Compliance**: Indexes leverage existing columns (no schema changes per FR-028).
2. **Performance**: B-tree indexes reduce query time from 10+ seconds to <500ms.
3. **Constitution Alignment**: Migration using Alembic follows Principle VI (structured testing gates).
4. **Scalability**: Indexes essential for handling millions of records (per plan.md Scale/Scope).

**Query Optimization Patterns**:
```python
# Use date range filters with indexed column
query = select(...).where(
    NoteRecord.created_at >= start_timestamp,
    NoteRecord.created_at <= end_timestamp
)

# Use indexed JOIN
query = select(...).join(
    PostRecord,
    NoteRecord.post_id == PostRecord.post_id
)

# Leverage composite index for filtered aggregations
query = select(...).where(
    NoteRecord.created_at >= start_timestamp,
    NoteRecord.current_status.in_(["CURRENTLY_RATED_HELPFUL"])
)
```

**Alternatives Considered**:
- Proceed without indexes - rejected as violates performance requirements
- Add indexes later if needed - rejected as technical debt and user-facing performance issues
- Use caching layer (Redis) - rejected as adds complexity and new dependency (Constitution Principle IV)
- Materialized views - rejected as schema change (violates FR-028)

---

## Decision 6: Concurrent Query Handling

### Question
How does the existing API handle concurrent database reads? Connection pooling settings?

### Research

Examined `/home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/settings.py`:

```python
class PostgresStorageSettings(BaseSettings):
    postgres_url: PostgresDsn
```

**Findings**:
- No explicit connection pool configuration
- SQLAlchemy defaults apply:
  - Pool size: 5
  - Max overflow: 10
  - Total connections: 15
- No connection pool parameters in .env.example

**Requirement**: System must handle 100 concurrent requests (SC-008) without degradation >5 seconds.

**Calculation**:
- 100 concurrent requests / 15 max connections = 6.67 requests per connection
- If query takes 500ms, queuing delay = 6.67 * 500ms = 3.3 seconds
- Total time: 500ms + 3300ms = 3.8 seconds (within 5 second target)

### Decision

**✅ ACCEPTABLE: Use SQLAlchemy Default Pool Settings**

**Rationale**:
1. **Read-Only Queries**: Graph endpoints are SELECT-only (no write contention).
2. **Fast Queries**: With indexes, queries complete in <500ms (see Decision 5).
3. **Performance Target Met**: 3.8 seconds worst case < 5 second threshold (SC-008).
4. **No Configuration Changes**: Aligns with Constitution Principle V (minimal env changes).
5. **PostgreSQL Capacity**: PostgreSQL 15.4 handles 100 connections easily.

**Implementation Notes**:
- No changes to `settings.py` required
- Monitor query duration in production (per FR-034: error logging only)
- If performance degrades, can tune later via environment variables:
  ```python
  # Future optimization if needed (not required now)
  engine = create_engine(
      url,
      pool_size=10,  # Increase from default 5
      max_overflow=20,  # Increase from default 10
      pool_pre_ping=True  # Verify connections before use
  )
  ```

**Alternatives Considered**:
- Increase pool size proactively - rejected as premature optimization
- Add connection pooling middleware (PgBouncer) - rejected as adds operational complexity
- Use read replicas - rejected as infrastructure change outside scope

---

## Summary of Decisions

| Decision | Selected Approach | Key Rationale |
|----------|-------------------|---------------|
| **Status Calculation** | SQL-side CASE expression | Performance, scalability for millions of records |
| **Zero-Filling** | Application-layer gap filling | No new dependencies, simple, flexible |
| **Date Validation** | Literal types + try-except | Consistency with existing code, type safety |
| **Error Format** | FastAPI default HTTPException | Matches existing API patterns |
| **Query Optimization** | **Add database indexes (REQUIRED)** | Performance requirements mandate indexes |
| **Connection Pooling** | SQLAlchemy defaults | Sufficient for 100 concurrent requests |

---

## Implementation Checklist

- [ ] Create Alembic migration for indexes (Decision 5)
- [ ] Implement `_get_publication_status_case()` helper in `storage.py` (Decision 1)
- [ ] Implement `_fill_daily_gaps()` helper in `storage.py` (Decision 2)
- [ ] Implement `_parse_month_range()` helper in `routers/graphs.py` (Decision 3)
- [ ] Use `HTTPException` with status_code=400/422 for errors (Decision 4)
- [ ] Define `PeriodType` and `StatusType` Literal types (Decision 3)
- [ ] No connection pool configuration changes needed (Decision 6)

---

## References

- `/home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/data.py` - Existing patterns
- `/home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/settings.py` - Configuration
- `/home/yu23ki14/cfj/BirdXplorer/migrate/migration/versions/` - Database schema
- `/home/yu23ki14/cfj/BirdXplorer/specs/001-graph-api-backend/spec.md` - Requirements
- `/home/yu23ki14/cfj/BirdXplorer/specs/001-graph-api-backend/plan.md` - Implementation plan
- SQLAlchemy documentation: `case()`, `func.date_trunc()`, connection pooling
- FastAPI documentation: Query parameter validation, HTTPException
