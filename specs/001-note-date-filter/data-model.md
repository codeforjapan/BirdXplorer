# Data Model: Note Date Filter

**Feature**: 001-note-date-filter
**Date**: 2026-01-21

## Overview

This feature does not introduce new database entities. It adds a configuration file and modifies the filtering logic for existing data flow.

---

## Configuration Schema

### settings.json

**Location**: `etl/seed/settings.json`

```json
{
  "filter": {
    "languages": ["ja", "en"],
    "keywords": [],
    "date_range": {
      "start_millis": 1704067200000
    }
  },
  "description": "Note filtering configuration. filter.date_range.start_millis is required."
}
```

### Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `filter` | object | Yes | Container for all filter settings |
| `filter.languages` | string[] | Yes | List of allowed language codes (e.g., `["ja", "en"]`) |
| `filter.keywords` | string[] | Yes | Keywords for matching. Empty array = language-only filter |
| `filter.date_range` | object | Yes | Date filtering configuration |
| `filter.date_range.start_millis` | number | **Yes** | Start timestamp in milliseconds (UTC). Notes before this are filtered |
| `description` | string | No | Human-readable description of the config |

### Validation Rules

| Rule | Error Type | Message |
|------|------------|---------|
| `settings.json` must exist | `FileNotFoundError` | "Settings file not found: {path}" |
| `filter.date_range.start_millis` must be set | `ValueError` | "filter.date_range.start_millis is required in settings.json" |
| `start_millis` must be a valid number | `TypeError` | (implicit from JSON parsing) |

---

## Existing Entities (Reference)

### RowNoteRecord (row_notes table)

Source table for note transformation. Relevant fields:

| Field | Type | Description |
|-------|------|-------------|
| `note_id` | string | Primary key |
| `created_at_millis` | BigInteger | Note creation timestamp (milliseconds, UTC) |
| `summary` | string | Note text content |
| `language` | string | Detected language code |

### NoteRecord (notes table)

Destination table. All notes are written here regardless of filter status:

| Field | Type | Description |
|-------|------|-------------|
| `note_id` | string | Primary key |
| `created_at` | BigInteger | Copied from `created_at_millis` |
| `language` | string | Detected language |
| `summary` | string | Note text |

---

## Data Flow

```
┌─────────────────┐
│   row_notes     │
│ (source table)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ note-transform  │
│    Lambda       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│     notes       │     │ settings.json    │
│ (dest table)    │     │ filter config    │
└────────┬────────┘     └────────┬─────────┘
         │                       │
         │  ◄────────────────────┘
         │  (filter check)
         │
    ┌────┴────┐
    │ Filter  │
    │ Chain   │
    └────┬────┘
         │
    ┌────┴────────────────────┐
    │                         │
    ▼                         ▼
┌─────────┐           ┌───────────┐
│ PASS    │           │ FILTERED  │
│         │           │           │
│ Send to │           │ Log skip  │
│ topic-  │           │ reason    │
│ detect- │           │           │
│ queue   │           │ (no queue │
│         │           │  message) │
└─────────┘           └───────────┘
```

---

## Filter Chain Logic

```python
# Pseudocode for filter evaluation
for note in successfully_transformed_notes:
    # Step 1: Language filter
    if note.language not in settings.filter.languages:
        log("language skip")
        continue

    # Step 2: Keyword filter (if keywords defined)
    if settings.filter.keywords and not matches_any_keyword(note.summary):
        log("keyword skip")
        continue

    # Step 3: Date filter
    if note.created_at_millis < settings.filter.date_range.start_millis:
        log("date skip")
        continue

    # All filters passed
    send_to_topic_detect_queue(note)
```

---

## Timestamp Reference

| Date (UTC) | Milliseconds |
|------------|--------------|
| 2022-01-01 00:00:00 | 1640995200000 |
| 2023-01-01 00:00:00 | 1672531200000 |
| 2024-01-01 00:00:00 | 1704067200000 |
| 2024-06-01 00:00:00 | 1717200000000 |
| 2025-01-01 00:00:00 | 1735689600000 |

**Conversion (Python)**:
```python
from datetime import datetime, timezone

# To milliseconds
dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
millis = int(dt.timestamp() * 1000)  # 1704067200000

# From milliseconds
millis = 1704067200000
dt = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
```
