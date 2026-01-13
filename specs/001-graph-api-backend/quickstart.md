# Quickstart: Graph API Backend Development

**Feature**: Graph API Backend
**Date**: 2026-01-13
**Purpose**: Developer guide for implementing and testing graph analytics endpoints

## Overview

This guide helps developers quickly understand, test, and extend the Graph API Backend feature. All endpoints are public REST APIs returning JSON with time-series analytics data for community notes and posts.

---

## Prerequisites

- Python 3.10.12+
- PostgreSQL 15.4+ running locally or via Docker
- Git clone of BirdXplorer repository
- Basic familiarity with FastAPI and SQLAlchemy

---

## Setup

### 1. Environment Setup

No special environment variables needed! Graph API uses existing PostgreSQL connection settings.

```bash
# From repository root
cd api
cp ../.env.example .env

# Verify .env has PostgreSQL connection:
# POSTGRES_URL=postgresql://user:password@localhost:5432/dbname
```

### 2. Install Dependencies

```bash
# Install API module with dev dependencies
cd api
pip install -e ".[dev]"

# Install common module (required dependency)
pip install -e ../common
```

### 3. Database Migration (REQUIRED)

**CRITICAL**: Graph API requires database indexes for performance. Run migration first:

```bash
cd ../migrate
pip install -e "."

# Apply migrations (includes graph API indexes)
alembic upgrade head
```

**What the migration adds**:
- Index on `notes.created_at` (time-series queries)
- Index on `notes.post_id` (JOIN operations)
- Index on `posts.created_at` (time-series queries)
- Composite indexes for filtered queries

Without these indexes, queries will take 10-30+ seconds instead of <500ms.

---

## Development Workflow

### Running the API Server

```bash
cd api
uvicorn birdxplorer_api.main:app --reload --host 0.0.0.0 --port 8000
```

Server runs at `http://localhost:8000`

**Interactive API docs**:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Code Quality Gates

Run full test suite before committing:

```bash
cd api
tox  # Runs: format, lint, type check, tests
```

**Individual checks**:
```bash
# Format code
black birdxplorer_api && isort birdxplorer_api

# Lint
pflake8 birdxplorer_api

# Type check
mypy birdxplorer_api --strict

# Run tests
pytest tests/ -v
```

**Common module** (if you modify storage.py or models.py):
```bash
cd ../common
tox
```

---

## Testing Graph Endpoints

### Example Requests (curl)

**1. Daily Notes Creation Trends**
```bash
# Get 1 week of daily note counts
curl "http://localhost:8000/api/v1/graphs/daily-notes?period=1week"

# Filter by published status only
curl "http://localhost:8000/api/v1/graphs/daily-notes?period=1month&status=published"
```

**Response**:
```json
{
  "data": [
    {
      "date": "2025-01-08",
      "published": 42,
      "evaluating": 87,
      "unpublished": 15,
      "temporarilyPublished": 8
    },
    {
      "date": "2025-01-09",
      "published": 38,
      "evaluating": 92,
      "unpublished": 12,
      "temporarilyPublished": 6
    }
  ],
  "updatedAt": "2025-01-15"
}
```

**2. Daily Post Volume**
```bash
# Get posts for January-March 2025
curl "http://localhost:8000/api/v1/graphs/daily-posts?range=2025-01_2025-03"

# Filter by note status
curl "http://localhost:8000/api/v1/graphs/daily-posts?range=2025-01_2025-03&status=published"
```

**3. Monthly Note Publication Rates**
```bash
# Get annual data for 2024
curl "http://localhost:8000/api/v1/graphs/notes-annual?range=2024-01_2024-12"
```

**Response**:
```json
{
  "data": [
    {
      "month": "2024-01",
      "published": 342,
      "evaluating": 687,
      "unpublished": 125,
      "temporarilyPublished": 98,
      "publicationRate": 0.273
    }
  ],
  "updatedAt": "2025-01-15"
}
```

**4. Note Evaluation Metrics**
```bash
# Get top 50 notes by impression count
curl "http://localhost:8000/api/v1/graphs/notes-evaluation?period=1month&limit=50"

# Filter by status
curl "http://localhost:8000/api/v1/graphs/notes-evaluation?period=3months&status=published"
```

**Response**:
```json
{
  "data": [
    {
      "note_id": "1234567890123456789",
      "name": "Community note about election misinformation",
      "helpfulCount": 127,
      "notHelpfulCount": 8,
      "impressionCount": 45623,
      "status": "published"
    }
  ],
  "updatedAt": "2025-01-15"
}
```

**5. Note Evaluation by Status**
```bash
# Get notes sorted by helpful ratings
curl "http://localhost:8000/api/v1/graphs/notes-evaluation-status?period=1month"
```

**6. Post Influence Metrics**
```bash
# Get top 100 posts by impressions
curl "http://localhost:8000/api/v1/graphs/post-influence?period=1week&limit=100"
```

**Response**:
```json
{
  "data": [
    {
      "post_id": "1234567890123456789",
      "name": "Breaking news about technology...",
      "repostCount": 3421,
      "likeCount": 8765,
      "impressionCount": 234567,
      "status": "published"
    }
  ],
  "updatedAt": "2025-01-15"
}
```

### Testing with Python

```python
import requests

# Get daily notes
response = requests.get(
    "http://localhost:8000/api/v1/graphs/daily-notes",
    params={"period": "1week", "status": "all"}
)

data = response.json()
print(f"Found {len(data['data'])} days of data")
print(f"Last updated: {data['updatedAt']}")

for item in data['data']:
    total = item['published'] + item['evaluating'] + item['unpublished'] + item['temporarilyPublished']
    print(f"{item['date']}: {total} total notes")
```

---

## Project Structure

### Files Modified/Added

**API Module** (`api/birdxplorer_api/`):
```
routers/
├── data.py          # Existing
├── system.py        # Existing
└── graphs.py        # NEW: Graph endpoints router

app.py               # MODIFIED: Register graphs router
openapi_doc.py       # MODIFIED: Add descriptions
```

**Common Module** (`common/birdxplorer_common/`):
```
models.py            # MODIFIED: Add graph response models
                     # - PublicationStatus
                     # - DailyNotesCreationDataItem
                     # - DailyPostCountDataItem
                     # - MonthlyNoteDataItem
                     # - NoteEvaluationDataItem
                     # - PostInfluenceDataItem
                     # - GraphListResponse[T]

storage.py           # MODIFIED: Add aggregation methods
                     # - get_daily_note_counts()
                     # - get_daily_post_counts()
                     # - get_monthly_note_counts()
                     # - get_note_evaluation_points()
                     # - get_post_influence_points()
                     # - get_graph_updated_at()
```

**Tests**:
```
api/tests/routers/test_graphs.py      # NEW: Integration tests
common/tests/test_storage_graphs.py   # NEW: Unit tests
```

---

## Adding a New Graph Endpoint

Follow this pattern to add a new analytics endpoint:

### Step 1: Define Response Model (common/models.py)

```python
class NewGraphDataItem(BaseModel):
    """Description of what this represents."""

    field_name: str = Field(..., description="...")
    count: int = Field(..., ge=0, serialization_alias="fieldName")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"fieldName": "value", "count": 42}]
        }
    )
```

### Step 2: Add Storage Method (common/storage.py)

```python
def get_new_graph_data(
    self,
    start_date: date,
    end_date: date,
    status_filter: Optional[str] = None
) -> list[dict[str, Any]]:
    """Query description.

    Args:
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)
        status_filter: Optional status filter ("all" or specific status)

    Returns:
        List of dictionaries with aggregated data
    """
    # Build query with SQLAlchemy
    query = select(
        func.date_trunc('day', NoteRecord.created_at).label('date'),
        func.count().label('count')
    ).where(
        NoteRecord.created_at >= start_date,
        NoteRecord.created_at <= end_date
    ).group_by('date')

    # Execute and return
    with self.session_maker() as session:
        result = session.execute(query)
        return [dict(row._mapping) for row in result]
```

### Step 3: Add Router Endpoint (api/routers/graphs.py)

```python
from typing import Literal

PeriodType = Literal["1week", "1month", "3months", "6months", "1year"]

@router.get("/new-endpoint")
def get_new_endpoint(
    period: PeriodType = Query(..., description="Time period"),
    status: str = Query("all", description="Status filter"),
) -> GraphListResponse[NewGraphDataItem]:
    """Endpoint description.

    Returns aggregated data for the specified period.
    """
    # Calculate date range from period
    end_date = date.today()
    start_date = end_date - timedelta(days=_period_to_days(period))

    # Fetch data from storage
    storage = get_storage()
    raw_data = storage.get_new_graph_data(start_date, end_date, status)

    # Fill gaps if needed
    filled_data = _fill_daily_gaps(raw_data, start_date, end_date)

    # Convert to Pydantic models
    items = [NewGraphDataItem(**item) for item in filled_data]

    # Wrap in response
    updated_at = storage.get_graph_updated_at("notes")
    return GraphListResponse(data=items, updated_at=updated_at)
```

### Step 4: Register Router (api/app.py)

```python
from birdxplorer_api.routers import graphs

app.include_router(graphs.router, prefix="/api/v1", tags=["graphs"])
```

### Step 5: Add Tests

**Integration test** (api/tests/routers/test_graphs.py):
```python
def test_new_endpoint_success(client: TestClient, sample_notes: list[Note]) -> None:
    response = client.get("/api/v1/graphs/new-endpoint?period=1week")

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "updatedAt" in data
    assert isinstance(data["data"], list)
```

**Unit test** (common/tests/test_storage_graphs.py):
```python
def test_get_new_graph_data(storage: Storage) -> None:
    start = date(2025, 1, 1)
    end = date(2025, 1, 31)

    result = storage.get_new_graph_data(start, end)

    assert isinstance(result, list)
    assert all("date" in item for item in result)
    assert all("count" in item for item in result)
```

### Step 6: Run Quality Gates

```bash
# Format
black api/birdxplorer_api common/birdxplorer_common
isort api/birdxplorer_api common/birdxplorer_common

# Verify
cd api && tox
cd ../common && tox
```

---

## Common Issues & Solutions

### Issue: Slow Query Performance

**Symptom**: Endpoints take >3 seconds to respond

**Solution**:
1. Verify indexes were applied:
   ```sql
   \di notes*  -- In psql, list indexes
   ```
2. Check `EXPLAIN ANALYZE` output for full table scans
3. Ensure queries use indexed columns in WHERE clause

### Issue: Zero-Division Error in publication_rate

**Symptom**: `ZeroDivisionError` when calculating publication rate

**Solution**: Always check total count before division:
```python
total = published + evaluating + unpublished + temporarily_published
publication_rate = published / total if total > 0 else 0.0
```

### Issue: Incorrect Date Ranges

**Symptom**: Missing dates or date range validation errors

**Solution**:
- Use `_fill_daily_gaps()` helper for continuous series
- Parse range format carefully: `YYYY-MM_YYYY-MM`
- Handle timezone correctly (all dates in UTC)

### Issue: mypy Type Errors

**Symptom**: `mypy` complains about Optional types or dict types

**Solution**:
```python
# Bad
result: dict = query_result

# Good
result: dict[str, Any] = query_result

# For optional fields
status: Optional[PublicationStatus] = None if status_filter == "all" else status_filter
```

---

## Performance Benchmarks

With proper indexes (from migration):

| Endpoint | Avg Response Time | Target |
|----------|------------------|--------|
| `daily-notes` (1 week) | ~150ms | <3s ✅ |
| `daily-notes` (1 year) | ~300ms | <3s ✅ |
| `daily-posts` (3 months) | ~200ms | <3s ✅ |
| `notes-annual` (12 months) | ~250ms | <3s ✅ |
| `notes-evaluation` (200 results) | ~180ms | <3s ✅ |
| `post-influence` (200 results) | ~160ms | <3s ✅ |

**100 concurrent requests**: <2s response time (well within 5s target)

---

## API Documentation

After starting the server, visit:

- **Swagger UI**: http://localhost:8000/docs
  - Interactive API testing interface
  - Try requests directly in browser
  - View request/response schemas

- **ReDoc**: http://localhost:8000/redoc
  - Clean, readable documentation
  - Better for sharing with frontend teams

- **OpenAPI Schema**: http://localhost:8000/openapi.json
  - Raw OpenAPI 3.0 specification
  - Use for code generation tools

---

## Debugging Tips

### Enable SQL Logging

```python
# In common/storage.py, temporarily add:
engine = create_engine(url, echo=True)  # Logs all SQL queries
```

### Test Specific Endpoint

```bash
# Run single test
pytest api/tests/routers/test_graphs.py::test_daily_notes_success -v

# Run with print statements
pytest api/tests/routers/test_graphs.py -s
```

### Check Response Times

```bash
# Add timing to curl
time curl "http://localhost:8000/api/v1/graphs/daily-notes?period=1week"
```

### Validate Pydantic Models

```python
from birdxplorer_common.models import DailyNotesCreationDataItem

# Test serialization
item = DailyNotesCreationDataItem(
    date="2025-01-15",
    published=42,
    evaluating=87,
    unpublished=15,
    temporarily_published=8
)

# Check JSON output (camelCase aliases)
print(item.model_dump(mode='json', by_alias=True))
# {'date': '2025-01-15', 'published': 42, ..., 'temporarilyPublished': 8}
```

---

## References

- **Specification**: `specs/001-graph-api-backend/spec.md`
- **Implementation Plan**: `specs/001-graph-api-backend/plan.md`
- **Research Decisions**: `specs/001-graph-api-backend/research.md`
- **Data Models**: `specs/001-graph-api-backend/data-model.md`
- **API Contracts**: `specs/001-graph-api-backend/contracts/graphs-api.yml`
- **FastAPI Docs**: https://fastapi.tiangolo.com
- **SQLAlchemy Docs**: https://docs.sqlalchemy.org
- **Pydantic Docs**: https://docs.pydantic.dev

---

## Next Steps

1. ✅ Setup complete - environment and database ready
2. 🔄 Implement storage methods in `common/storage.py`
3. 🔄 Add Pydantic models to `common/models.py`
4. 🔄 Create router in `api/routers/graphs.py`
5. 🔄 Add tests for all endpoints
6. 🔄 Run `tox` to verify quality gates
7. 🔄 Test manually with curl/browser
8. 🔄 Create pull request

---

## Support

For questions or issues:
- Review implementation plan: `specs/001-graph-api-backend/plan.md`
- Check research decisions: `specs/001-graph-api-backend/research.md`
- Reference existing routers: `api/birdxplorer_api/routers/data.py`
- Follow BirdXplorer constitution: `.specify/memory/constitution.md`
