# Implementation Plan: Note Date Filter

**Branch**: `001-note-date-filter` | **Date**: 2026-01-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-note-date-filter/spec.md`
**Related Issue**: https://github.com/codeforjapan/BirdXplorer/issues/200

## Summary

Add date-based filtering to the `note-transform-lambda` to skip downstream processing (topic detection, post lookup) for notes older than a configured start date. All notes are still saved to the database; the filter only affects SQS queue forwarding. Configuration will be unified in a new `settings.json` file that consolidates language, keyword, and date filters.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: SQLAlchemy, birdxplorer_common, boto3 (SQS)
**Storage**: PostgreSQL 15.4+ (row_notes, notes tables)
**Testing**: pytest (via tox for format/lint/type/test)
**Target Platform**: AWS Lambda (Docker image deployment)
**Project Type**: ETL module within monorepo
**Performance Goals**: <5% impact on per-note processing time
**Constraints**: Must maintain backward compatibility with existing keywords.json during transition
**Scale/Scope**: Processes Community Notes data from TSV files dating back to 2022

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Modular Architecture | ✅ PASS | Changes confined to etl module only |
| II. Database-Centric Design | ✅ PASS | Uses existing PostgreSQL tables, no schema changes |
| III. Test-First Discipline | ✅ PASS | Tests required for load_settings(), check_date_filter(), integration |
| IV. Dependency Management | ✅ PASS | No new external dependencies |
| V. Environment Configuration | ✅ PASS | Uses seed/settings.json (file-based config, not env vars) |
| VI. Structured Testing Gates | ✅ PASS | Must pass tox (format, lint, type, tests) |
| VII. Python Standards | ✅ PASS | Black, isort, mypy --strict, snake_case |

**Gate Result**: PASS - No violations detected.

## Project Structure

### Documentation (this feature)

```text
specs/001-note-date-filter/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
etl/
├── seed/
│   ├── keywords.json        # Existing (deprecated after migration)
│   └── settings.json        # NEW: Unified filter configuration
├── src/birdxplorer_etl/
│   └── lib/lambda_handler/
│       └── note_transform_lambda.py  # MODIFIED: Add date filter
└── tests/
    └── test_note_transform_lambda.py # NEW: Tests for date filter
```

**Structure Decision**: Single module modification within existing etl structure. No new directories or architectural changes required.

## Complexity Tracking

> No violations to justify - all changes follow existing patterns.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | N/A | N/A |
