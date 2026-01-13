# Data Model: Graph API Backend

**Feature**: Graph API Backend
**Date**: 2026-01-13
**Purpose**: Define Pydantic response models and data entities for graph analytics endpoints

## Overview

This document specifies all Pydantic models to be added to `/home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py` for the graph API endpoints. All models follow existing BirdXplorer conventions: snake_case fields with camelCase aliases for JSON serialization.

---

## Model Hierarchy

```
GraphListResponse[T] (Generic wrapper)
├── DailyNotesCreationDataItem
├── DailyPostCountDataItem
├── MonthlyNoteDataItem
├── NoteEvaluationDataItem
└── PostInfluenceDataItem

PublicationStatus (Enum)
```

---

## 1. Publication Status Enum

**Purpose**: Derived status for community notes calculated from `current_status` and `has_been_helpfuled`.

```python
class PublicationStatus(str, Enum):
    """Derived publication status for community notes.

    Calculated from NoteRecord.current_status and NoteRecord.has_been_helpfuled:
    - published: current_status = CURRENTLY_RATED_HELPFUL
    - temporarilyPublished: has_been_helpfuled = True AND current_status IN (NEEDS_MORE_RATINGS, CURRENTLY_RATED_NOT_HELPFUL)
    - evaluating: current_status = NEEDS_MORE_RATINGS AND has_been_helpfuled = False
    - unpublished: all other cases
    """

    PUBLISHED = "published"
    TEMPORARILY_PUBLISHED = "temporarilyPublished"
    EVALUATING = "evaluating"
    UNPUBLISHED = "unpublished"
```

**Notes**:
- String enum for JSON serialization compatibility
- Value names use camelCase to match API response format (per clarifications and existing BirdXplorer patterns)
- NOT stored in database (derived at query time per FR-007)

---

## 2. DailyNotesCreationDataItem

**Purpose**: Daily aggregation of community note creation counts by publication status.

**Used by**: `GET /api/v1/graphs/daily-notes`

```python
class DailyNotesCreationDataItem(BaseModel):
    """Daily community note creation counts by publication status.

    Represents a single day's aggregated note creation data.
    """

    date: str = Field(
        ...,
        description="Date in YYYY-MM-DD format (UTC timezone)",
        examples=["2025-01-15"]
    )

    published: int = Field(
        ...,
        ge=0,
        description="Count of notes with published status on this date"
    )

    evaluating: int = Field(
        ...,
        ge=0,
        description="Count of notes with evaluating status on this date"
    )

    unpublished: int = Field(
        ...,
        ge=0,
        description="Count of notes with unpublished status on this date"
    )

    temporarily_published: int = Field(
        ...,
        ge=0,
        description="Count of notes with temporarily published status on this date",
        serialization_alias="temporarilyPublished"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{
                "date": "2025-01-15",
                "published": 42,
                "evaluating": 87,
                "unpublished": 15,
                "temporarilyPublished": 8
            }]
        }
    )
```

**Validation Rules** (from FR-008):
- All count fields must be non-negative integers
- Date must be in YYYY-MM-DD format
- Missing dates filled with zero counts (FR-016)

---

## 3. DailyPostCountDataItem

**Purpose**: Daily aggregation of post counts within a month range.

**Used by**: `GET /api/v1/graphs/daily-posts`

```python
class DailyPostCountDataItem(BaseModel):
    """Daily post counts within a specified month range.

    Represents post volume for a single day, optionally filtered by
    associated community note status.
    """

    date: str = Field(
        ...,
        description="Date in YYYY-MM-DD format (UTC timezone)",
        examples=["2025-01-15"]
    )

    post_count: int = Field(
        ...,
        ge=0,
        description="Total number of posts created on this date",
        serialization_alias="postCount"
    )

    status: Optional[PublicationStatus] = Field(
        None,
        description="Publication status of associated notes (if status filter applied)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{
                "date": "2025-01-15",
                "postCount": 1523,
                "status": "published"
            }]
        }
    )
```

**Validation Rules** (from FR-009):
- Post count must be non-negative
- Status is optional (None when status="all")
- Date range validated to not exceed constraints (FR-019)

---

## 4. MonthlyNoteDataItem

**Purpose**: Monthly aggregation of note counts with publication rate calculation.

**Used by**: `GET /api/v1/graphs/notes-annual`

```python
class MonthlyNoteDataItem(BaseModel):
    """Monthly community note counts with publication rate.

    Aggregates note creation data by month and calculates the percentage
    of notes that achieved published status.
    """

    month: str = Field(
        ...,
        description="Month in YYYY-MM format",
        examples=["2025-01"]
    )

    published: int = Field(
        ...,
        ge=0,
        description="Count of notes with published status in this month"
    )

    evaluating: int = Field(
        ...,
        ge=0,
        description="Count of notes with evaluating status in this month"
    )

    unpublished: int = Field(
        ...,
        ge=0,
        description="Count of notes with unpublished status in this month"
    )

    temporarily_published: int = Field(
        ...,
        ge=0,
        description="Count of notes with temporarily published status in this month",
        serialization_alias="temporarilyPublished"
    )

    publication_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Ratio of published notes to total notes (0.0 to 1.0). Returns 0.0 if no notes.",
        serialization_alias="publicationRate"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{
                "month": "2025-01",
                "published": 342,
                "evaluating": 687,
                "unpublished": 125,
                "temporarilyPublished": 98,
                "publicationRate": 0.273
            }]
        }
    )
```

**Validation Rules** (from FR-010, FR-024):
- All count fields must be non-negative
- publication_rate = published / (published + evaluating + unpublished + temporarilyPublished)
- If total notes is 0, publication_rate must be 0.0 (FR-024: zero-division handling)
- publication_rate must be between 0.0 and 1.0 inclusive

---

## 5. NoteEvaluationDataItem

**Purpose**: Individual note metrics for evaluation analysis (bubble chart data).

**Used by**:
- `GET /api/v1/graphs/notes-evaluation`
- `GET /api/v1/graphs/notes-evaluation-status`

```python
class NoteEvaluationDataItem(BaseModel):
    """Individual community note evaluation metrics.

    Represents a single note's effectiveness metrics including ratings
    and reach (impression count from associated post).
    """

    note_id: NoteId = Field(
        ...,
        description="Unique identifier for the community note"
    )

    name: str = Field(
        ...,
        description="Note display name (derived from summary or note_id)",
        max_length=200
    )

    helpful_count: int = Field(
        ...,
        ge=0,
        description="Number of 'helpful' ratings received",
        serialization_alias="helpfulCount"
    )

    not_helpful_count: int = Field(
        ...,
        ge=0,
        description="Number of 'not helpful' ratings received",
        serialization_alias="notHelpfulCount"
    )

    impression_count: int = Field(
        ...,
        ge=0,
        description="Impression count from associated post (0 if no post or NULL impression)",
        serialization_alias="impressionCount"
    )

    status: PublicationStatus = Field(
        ...,
        description="Current publication status of the note"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{
                "note_id": "1234567890123456789",
                "name": "Community note about election misinformation",
                "helpfulCount": 127,
                "notHelpfulCount": 8,
                "impressionCount": 45623,
                "status": "published"
            }]
        }
    )
```

**Validation Rules** (from FR-011, FR-023):
- All count fields must be non-negative
- impression_count defaults to 0 if post is NULL or impression_count is NULL (FR-023)
- name derived from note summary (first 200 chars) or fallback to note_id
- Sorting: impression_count DESC, then helpful_count DESC (FR-013)
- Sorting (status variant): helpful_count DESC, then not_helpful_count ASC (FR-014)

---

## 6. PostInfluenceDataItem

**Purpose**: Post engagement metrics for influence analysis.

**Used by**: `GET /api/v1/graphs/post-influence`

```python
class PostInfluenceDataItem(BaseModel):
    """Post engagement and influence metrics.

    Represents a single post's reach and impact through engagement
    metrics (reposts, likes, impressions) and associated note status.
    """

    post_id: PostId = Field(
        ...,
        description="Unique identifier for the post"
    )

    name: str = Field(
        ...,
        description="Post display name (derived from text or post_id)",
        max_length=200
    )

    repost_count: int = Field(
        ...,
        ge=0,
        description="Number of reposts/retweets",
        serialization_alias="repostCount"
    )

    like_count: int = Field(
        ...,
        ge=0,
        description="Number of likes/favorites",
        serialization_alias="likeCount"
    )

    impression_count: int = Field(
        ...,
        ge=0,
        description="Total impressions/views (0 if NULL)",
        serialization_alias="impressionCount"
    )

    status: PublicationStatus = Field(
        ...,
        description="Publication status of associated community note (unpublished if no note)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{
                "post_id": "1234567890123456789",
                "name": "Breaking news about technology...",
                "repostCount": 3421,
                "likeCount": 8765,
                "impressionCount": 234567,
                "status": "published"
            }]
        }
    )
```

**Validation Rules** (from FR-012, FR-023):
- All count fields must be non-negative
- impression_count defaults to 0 if NULL (FR-023)
- status defaults to "unpublished" if post has no associated notes (FR-012)
- name derived from post text (first 200 chars) or fallback to post_id
- Sorting: impression_count DESC (FR-015)

---

## 7. GraphListResponse (Generic)

**Purpose**: Standard wrapper for all graph API responses with metadata.

**Used by**: All 6 graph endpoints

```python
from typing import TypeVar, Generic
from pydantic import BaseModel, Field

T = TypeVar('T')

class GraphListResponse(BaseModel, Generic[T]):
    """Generic response wrapper for graph API endpoints.

    Provides consistent response structure with data array and metadata.
    All graph endpoints return this wrapper with specific data item type.
    """

    data: list[T] = Field(
        ...,
        description="Array of data items (type varies by endpoint)"
    )

    updated_at: str = Field(
        ...,
        description="Last update timestamp in YYYY-MM-DD format (UTC). Derived from MAX(created_at) of source table.",
        serialization_alias="updatedAt",
        examples=["2025-01-15"]
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{
                "data": [
                    {
                        "date": "2025-01-15",
                        "published": 42,
                        "evaluating": 87,
                        "unpublished": 15,
                        "temporarilyPublished": 8
                    }
                ],
                "updatedAt": "2025-01-15"
            }]
        }
    )
```

**Validation Rules** (from FR-021, FR-022, FR-026, FR-027):
- data must be a list (can be empty per FR-027)
- updated_at format is YYYY-MM-DD in UTC (FR-021)
- updated_at derived from MAX(created_at) of notes or posts table (FR-022)
- Response format consistent across all endpoints (FR-026)

**Usage Examples**:
```python
# Type-safe response models
GraphListResponse[DailyNotesCreationDataItem]
GraphListResponse[DailyPostCountDataItem]
GraphListResponse[MonthlyNoteDataItem]
GraphListResponse[NoteEvaluationDataItem]
GraphListResponse[PostInfluenceDataItem]
```

---

## Data Relationships

### Database Tables → Response Models

```
NoteRecord (storage.py)
├── created_at → date field in Daily/Monthly items
├── current_status + has_been_helpfuled → status (derived PublicationStatus)
├── helpful_count → helpful_count in NoteEvaluationDataItem
├── not_helpful_count → not_helpful_count in NoteEvaluationDataItem
├── summary → name in NoteEvaluationDataItem
└── note_id → note_id in NoteEvaluationDataItem

PostRecord (storage.py)
├── created_at → date field in DailyPostCountDataItem
├── impression_count → impression_count in NoteEvaluationDataItem & PostInfluenceDataItem
├── repost_count → repost_count in PostInfluenceDataItem
├── like_count → like_count in PostInfluenceDataItem
├── text → name in PostInfluenceDataItem
└── post_id → post_id in PostInfluenceDataItem

NoteRecord JOIN PostRecord (via post_id)
└── impression_count from PostRecord → NoteEvaluationDataItem.impression_count
```

### Aggregation Flow

```
SQL Aggregation (storage.py methods)
    ↓
Python Dictionaries (raw query results)
    ↓
Gap Filling (application layer per research.md Decision 2)
    ↓
Pydantic Model Instantiation (validation + serialization)
    ↓
GraphListResponse[T] (wrapped with updated_at metadata)
    ↓
FastAPI JSON Response (camelCase field aliases)
```

---

## Field Naming Conventions

Following BirdXplorer standards (observed in `/home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py`):

| Python Field Name | JSON Field Name (alias) | Example |
|-------------------|-------------------------|---------|
| `temporarily_published` | `temporarilyPublished` | Counts |
| `publication_rate` | `publicationRate` | Rate value |
| `post_count` | `postCount` | Count value |
| `helpful_count` | `helpfulCount` | Rating count |
| `not_helpful_count` | `notHelpfulCount` | Rating count |
| `impression_count` | `impressionCount` | Engagement metric |
| `repost_count` | `repostCount` | Engagement metric |
| `like_count` | `likeCount` | Engagement metric |
| `updated_at` | `updatedAt` | Timestamp |
| `note_id` | `note_id` | ID fields (no alias) |
| `post_id` | `post_id` | ID fields (no alias) |

**Rule**: Use `serialization_alias` for camelCase in JSON output while keeping snake_case for Python code.

---

## Validation Summary

All models include:
- ✅ Type annotations for strict mypy checking
- ✅ Field descriptions for OpenAPI documentation
- ✅ Validation constraints (ge=0, le=1.0, max_length)
- ✅ Example values for API documentation
- ✅ Serialization aliases for camelCase JSON output
- ✅ ConfigDict for Pydantic v2 configuration

All models comply with:
- BirdXplorer constitution (Python 3.10+, strict typing, snake_case)
- Existing codebase patterns (BaseModel, Field, ConfigDict)
- Feature specification requirements (FR-001 through FR-035)

---

## Testing Considerations

Each model should be tested for:
1. **Serialization**: Python dict → Pydantic model → JSON (with camelCase)
2. **Validation**: Boundary cases (negative counts, invalid dates, NULL handling)
3. **Type Safety**: mypy --strict compliance
4. **Default Values**: Optional fields, zero-division in publication_rate
5. **Example Validity**: json_schema_extra examples must validate

Example test structure:
```python
def test_daily_notes_creation_data_item_serialization():
    item = DailyNotesCreationDataItem(
        date="2025-01-15",
        published=42,
        evaluating=87,
        unpublished=15,
        temporarily_published=8
    )
    json_data = item.model_dump(mode='json', by_alias=True)
    assert json_data["temporarilyPublished"] == 8  # camelCase alias
    assert "temporarily_published" not in json_data  # no snake_case
```

---

## Implementation Checklist

- [ ] Add `PublicationStatus` enum to `models.py`
- [ ] Add `DailyNotesCreationDataItem` model to `models.py`
- [ ] Add `DailyPostCountDataItem` model to `models.py`
- [ ] Add `MonthlyNoteDataItem` model to `models.py`
- [ ] Add `NoteEvaluationDataItem` model to `models.py`
- [ ] Add `PostInfluenceDataItem` model to `models.py`
- [ ] Add `GraphListResponse[T]` generic model to `models.py`
- [ ] Update `models.py` `__all__` export list
- [ ] Verify strict mypy compliance (`mypy common/birdxplorer_common --strict`)
- [ ] Add unit tests in `common/tests/` for each model
- [ ] Verify serialization with camelCase aliases

---

## References

- Specification: `/home/yu23ki14/cfj/BirdXplorer/specs/001-graph-api-backend/spec.md`
- Plan: `/home/yu23ki14/cfj/BirdXplorer/specs/001-graph-api-backend/plan.md`
- Research: `/home/yu23ki14/cfj/BirdXplorer/specs/001-graph-api-backend/research.md`
- Existing Models: `/home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py`
- Pydantic v2 Documentation: https://docs.pydantic.dev/latest/
