# Quickstart: Note Date Filter

**Feature**: 001-note-date-filter
**Date**: 2026-01-21

## Prerequisites

- Python 3.10+
- PostgreSQL 15.4+ running
- ETL module dependencies installed

## Setup

### 1. Install Dependencies

```bash
cd BirdXplorer/etl
pip install -e ".[dev]"
pip install -e ../common
```

### 2. Create settings.json

Create `etl/seed/settings.json`:

```json
{
  "filter": {
    "languages": ["ja", "en"],
    "keywords": [],
    "start_millis": 1704067200000
  },
  "description": "Filter notes from 2024-01-01 onwards"
}
```

**Note**: `filter.start_millis` is required. Use this Python snippet to calculate:

```python
from datetime import datetime, timezone
dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
print(int(dt.timestamp() * 1000))  # 1704067200000
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your database credentials
```

## Running Tests

```bash
cd BirdXplorer/etl

# Run all quality checks
tox

# Run specific test file
python -m pytest tests/test_note_transform_lambda.py -v

# Run single test
python -m pytest tests/test_note_transform_lambda.py::TestCheckDateFilter::test_within_range -v
```

## Local Testing

### Test the Date Filter Function

```python
from birdxplorer_etl.lib.lambda_handler.note_transform_lambda import check_date_filter

# Test: Note within range (should return True)
result = check_date_filter(
    created_at_millis=1710000000000,  # March 2024
    start_millis=1704067200000        # Jan 1, 2024
)
print(f"Within range: {result}")  # True

# Test: Note before range (should return False)
result = check_date_filter(
    created_at_millis=1672531200000,  # Jan 1, 2023
    start_millis=1704067200000        # Jan 1, 2024
)
print(f"Before range: {result}")  # False
```

### Test Settings Loading

```python
from birdxplorer_etl.lib.lambda_handler.note_transform_lambda import load_settings

settings = load_settings()
print(f"Languages: {settings['filter']['languages']}")
print(f"Start millis: {settings['filter']['start_millis']}")
```

## Verification Checklist

- [ ] `settings.json` exists in `etl/seed/`
- [ ] `start_millis` is set to desired cutoff date
- [ ] `tox` passes all checks (format, lint, type, test)
- [ ] Logs show date filter skip messages for old notes

## Common Issues

### FileNotFoundError: Settings file not found

**Cause**: `settings.json` not in expected location
**Solution**: Ensure file is at `etl/seed/settings.json`

### ValueError: filter.start_millis is required

**Cause**: Missing required field in settings.json
**Solution**: Add `start_millis` to `filter` object

### TypeError with created_at_millis

**Cause**: Database returns Decimal type
**Solution**: The code converts to int automatically. If testing manually, use `int(value)`.

## Next Steps

After verifying local setup:

1. Run `/speckit.tasks` to generate implementation tasks
2. Follow task order in `tasks.md`
3. Create PR after all tests pass
