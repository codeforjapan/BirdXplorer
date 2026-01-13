# Implementation Plan: Graph API Backend

**Branch**: `001-graph-api-backend` | **Date**: 2026-01-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-graph-api-backend/spec.md`

## Summary

Add 6 new graph API endpoints to the existing BirdXplorer API module to provide analytics data for community notes and posts. The endpoints will aggregate existing data from the `notes` and `posts` tables to generate time-series visualizations and evaluation metrics. All endpoints are public (no authentication), use existing database schema, and follow FastAPI/SQLAlchemy patterns established in the codebase.

**Primary Requirement**: Implement read-only analytics endpoints that calculate derived publication statuses and aggregate metrics over time periods.

**Technical Approach**: Extend the existing `api` module with a new `/routers/graphs.py` router, add response models to `common/models.py`, implement aggregation queries in `common/storage.py` using SQLAlchemy's `func.date_trunc()` and `case()` expressions for efficient database-side computation.

## Technical Context

**Language/Version**: Python 3.10.12+ (existing project standard)
**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, Pydantic (existing stack)
**Storage**: PostgreSQL 15.4+ with existing `notes` and `posts` tables
**Testing**: pytest with tox, mypy --strict, black, isort, pflake8 (existing quality gates)
**Target Platform**: Linux server (Docker containerized API service)
**Project Type**: Multi-module (api + common modules)
**Performance Goals**:
- <3 seconds for time-series endpoints (daily/monthly aggregations)
- <3 seconds for top-N queries (note evaluation, post influence)
- 100 concurrent requests without degradation >5 seconds
**Constraints**:
- Use existing database tables only (no migrations)
- Public endpoints (no authentication/rate limiting per clarifications)
- Minimal observability (error logging only)
- Breaking changes acceptable (no versioning constraints)
**Scale/Scope**:
- 6 new REST endpoints under `/api/v1/graphs/` prefix
- ~5-10 new Pydantic response models in common
- ~6 new storage methods for aggregations
- Target: millions of notes/posts with proper indexing

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Compliance Review

| Principle | Status | Notes |
|-----------|--------|-------|
| **I. Modular Architecture** | ✅ PASS | Changes confined to `api` (new router) and `common` (models + storage methods). No cross-module violations. |
| **II. Database-Centric Design** | ✅ PASS | Uses PostgreSQL as single source of truth. All aggregations performed via SQLAlchemy ORM with strict types. |
| **III. Test-First Discipline** | ✅ PASS | Will add pytest tests for new endpoints, storage methods. Tox gates enforced (format, lint, type, tests). |
| **IV. Dependency Management** | ✅ PASS | No new dependencies required. Uses existing FastAPI, SQLAlchemy, Pydantic. Common module unchanged dependency-wise. |
| **V. Environment Configuration** | ✅ PASS | No new environment variables needed. Uses existing PostgreSQL connection settings. |
| **VI. Structured Testing Gates** | ✅ PASS | All new code will pass tox (black, isort, pflake8, mypy --strict, pytest). CI workflow unchanged. |
| **VII. Python Standards** | ✅ PASS | Snake_case functions, PascalCase classes, 120 char lines, strict mypy, custom exceptions inherit BaseError. |

**Result**: ✅ **ALL GATES PASS** - No constitution violations. Feature aligns perfectly with existing architecture.

## Project Structure

### Documentation (this feature)

```text
specs/001-graph-api-backend/
├── plan.md              # This file
├── research.md          # Phase 0: Technical decisions and patterns (NEXT)
├── data-model.md        # Phase 1: Response models and entities
├── quickstart.md        # Phase 1: Developer guide for using graph endpoints
├── contracts/           # Phase 1: OpenAPI schema fragments
│   ├── daily-notes.yml
│   ├── daily-posts.yml
│   ├── notes-annual.yml
│   ├── notes-evaluation.yml
│   ├── notes-evaluation-status.yml
│   └── post-influence.yml
└── tasks.md             # Phase 2: NOT created by /speckit.plan (use /speckit.tasks)
```

### Source Code (repository root)

```text
api/
├── birdxplorer_api/
│   ├── routers/
│   │   ├── data.py          # Existing router
│   │   ├── system.py        # Existing router
│   │   └── graphs.py        # NEW: Graph endpoints router
│   ├── app.py               # MODIFY: Register graphs router
│   └── openapi_doc.py       # MODIFY: Add graph endpoint descriptions

common/
├── birdxplorer_common/
│   ├── models.py            # MODIFY: Add graph response models
│   │                        # - DailyNotesCreationDataItem
│   │                        # - DailyPostCountDataItem
│   │                        # - MonthlyNoteDataItem
│   │                        # - NoteEvaluationDataItem
│   │                        # - PostInfluenceDataItem
│   │                        # - GraphListResponse[T]
│   └── storage.py           # MODIFY: Add aggregation methods
│                            # - get_daily_note_counts()
│                            # - get_daily_post_counts()
│                            # - get_monthly_note_counts()
│                            # - get_note_evaluation_points()
│                            # - get_post_influence_points()
│                            # - get_graph_updated_at()

api/tests/
└── routers/
    └── test_graphs.py       # NEW: Integration tests for graph endpoints

common/tests/
└── test_storage_graphs.py   # NEW: Unit tests for aggregation methods
```

**Structure Decision**: The existing BirdXplorer multi-module architecture (api, common, etl, migrate) perfectly accommodates this feature. Graph endpoints are API-layer concerns (routing, validation, serialization) implemented in `api/routers/graphs.py`, while data aggregation logic belongs in `common/storage.py` for reusability. Response models go in `common/models.py` following the established pattern where common owns all Pydantic models.

## Complexity Tracking

> No violations detected. This section intentionally left empty as all Constitution gates pass.

## Phase 0: Research & Technical Decisions

### Research Tasks

The following technical decisions need investigation and documentation in `research.md`:

1. **Status Calculation Strategy**
   - **Question**: How to efficiently implement the 4-way status derivation logic (`published`, `temporarilyPublished`, `evaluating`, `unpublished`) in SQLAlchemy?
   - **Research**: Evaluate `case()` expression vs. Python post-processing. Benchmark query performance.
   - **Decision Needed**: SQL-side CASE vs. application-side logic

2. **Time Series Zero-Filling**
   - **Question**: How to generate continuous date series with zero counts for missing days/months?
   - **Research**: PostgreSQL `generate_series()` + LEFT JOIN vs. Python pandas vs. application-layer gap filling
   - **Decision Needed**: Database-side vs. application-side gap filling

3. **Date Range Validation**
   - **Question**: How to validate and parse period ("1week", "1month") and range ("YYYY-MM_YYYY-MM") parameters?
   - **Research**: FastAPI query parameter validation patterns, Pydantic validators, custom parameter types
   - **Decision Needed**: Validation approach (Pydantic model, depends(), or inline)

4. **Error Response Format**
   - **Question**: What is the existing BirdXplorer error response format?
   - **Research**: Examine `api/routers/data.py` and `api/routers/system.py` for existing error handling patterns
   - **Decision Needed**: Match existing format or implement fallback structure

5. **Aggregation Query Optimization**
   - **Question**: How to optimize date_trunc + JOIN + status CASE queries for millions of records?
   - **Research**: Check existing indexes on `notes.created_at`, `notes.post_id`, `posts.created_at`. Evaluate need for new indexes.
   - **Decision Needed**: Index recommendations (if any)

6. **Concurrent Query Handling**
   - **Question**: How does the existing API handle concurrent database reads? Connection pooling settings?
   - **Research**: Review `common/settings.py` PostgreSQL connection configuration
   - **Decision Needed**: Verify existing pool size adequate or recommend tuning

**Research Agents to Dispatch**:
- Agent 1: "Analyze existing error response patterns in api/routers/data.py for Graph API consistency"
- Agent 2: "Research SQLAlchemy case() expressions and date_trunc() aggregation best practices for time-series analytics"
- Agent 3: "Investigate existing database indexes on notes and posts tables relevant to graph queries"
- Agent 4: "Document FastAPI query parameter validation patterns for period enums and date range parsing"

## Phase 1: Design & Contracts

### Data Model Design (`data-model.md`)

Extract from feature spec FR-007 and Key Entities:

**Core Entities**:
1. **Publication Status** (derived enum)
   - Values: `published`, `temporarilyPublished`, `evaluating`, `unpublished`
   - Calculation: CASE expression on `current_status` + `has_been_helpfuled`

2. **DailyNotesCreationDataItem**
   - Fields: `date` (YYYY-MM-DD), `published` (int), `evaluating` (int), `unpublished` (int), `temporarilyPublished` (int)

3. **DailyPostCountDataItem**
   - Fields: `date` (YYYY-MM-DD), `post_count` (int), `status` (PublicationStatus)

4. **MonthlyNoteDataItem**
   - Fields: `month` (YYYY-MM), `published` (int), `evaluating` (int), `unpublished` (int), `temporarilyPublished` (int), `publication_rate` (float)

5. **NoteEvaluationDataItem**
   - Fields: `note_id` (NoteId), `name` (str), `helpful_count` (int), `not_helpful_count` (int), `impression_count` (int), `status` (PublicationStatus)

6. **PostInfluenceDataItem**
   - Fields: `post_id` (PostId), `name` (str), `repost_count` (int), `like_count` (int), `impression_count` (int), `status` (PublicationStatus)

7. **GraphListResponse[T]** (generic)
   - Fields: `data` (List[T]), `updated_at` (str in YYYY-MM-DD format)

### API Contract Generation (`contracts/*.yml`)

For each endpoint in FR-001 through FR-006, generate OpenAPI 3.0 schema fragment:

**Endpoints**:
1. `GET /api/v1/graphs/daily-notes?period={period}&status={status}`
2. `GET /api/v1/graphs/daily-posts?range={range}&status={status}`
3. `GET /api/v1/graphs/notes-annual?range={range}&status={status}`
4. `GET /api/v1/graphs/notes-evaluation?period={period}&status={status}&limit={limit}`
5. `GET /api/v1/graphs/notes-evaluation-status?period={period}&status={status}`
6. `GET /api/v1/graphs/post-influence?period={period}&status={status}&limit={limit}`

**Common Parameters**:
- `period`: enum ["1week", "1month", "3months", "6months", "1year"]
- `range`: string pattern "YYYY-MM_YYYY-MM"
- `status`: enum ["all", "published", "evaluating", "unpublished", "temporarilyPublished"], default "all"
- `limit`: integer min=1 max=1000

**Common Responses**:
- 200: `GraphListResponse[{DataItem}]`
- 400: Error object (match existing format or `{"error": "...", "message": "..."}`)
- 500: Error object

### Quickstart Guide (`quickstart.md`)

Document:
1. **Setup**: No special setup needed (existing API environment)
2. **Development**: Run `tox` in `api` and `common` modules after changes
3. **Testing**: `pytest api/tests/routers/test_graphs.py -v`
4. **Example Requests**: curl examples for each endpoint with sample responses
5. **Adding a New Graph Endpoint**: Step-by-step guide (router function → storage method → model → tests)

### Agent Context Update

Run `.specify/scripts/bash/update-agent-context.sh claude` to add:
- New graph router endpoint patterns
- SQLAlchemy aggregation query patterns
- Pydantic generic response model pattern
- Date range validation approach

## Phase 2: Task Generation

NOT CREATED BY `/speckit.plan`. Use `/speckit.tasks` command after this plan is approved.

Expected task categories:
1. **Common Module Tasks**: Add models, add storage methods, add tests
2. **API Module Tasks**: Add graphs router, register router, update OpenAPI docs, add tests
3. **Documentation Tasks**: Update README if needed
4. **Testing Tasks**: Integration tests, performance validation

## Next Steps

1. ✅ Plan complete - awaiting approval
2. 🔄 Run `/speckit.tasks` to generate detailed task breakdown
3. ⏳ Execute tasks via `/speckit.implement`
4. ⏳ Run quality gates (`tox`) and manual testing
5. ⏳ Create pull request

## Notes

- **No database migrations needed**: All required columns exist in current schema
- **No new dependencies**: Entirely implementable with existing FastAPI + SQLAlchemy + Pydantic stack
- **Public endpoints**: No auth middleware to configure (per clarifications)
- **Error logging only**: No metrics/tracing instrumentation required (per clarifications)
- **Breaking changes OK**: No version pinning concerns (per clarifications)
