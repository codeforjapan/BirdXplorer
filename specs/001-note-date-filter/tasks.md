# Tasks: Note Date Filter

**Input**: Design documents from `/specs/001-note-date-filter/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md
**Related Issue**: https://github.com/codeforjapan/BirdXplorer/issues/200

**Tests**: Tests ARE requested per Constitution Principle III (Test-First Discipline) and plan.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **ETL Module**: `etl/src/birdxplorer_etl/`, `etl/tests/`, `etl/seed/`

---

## Phase 1: Setup

**Purpose**: Create configuration file and prepare test infrastructure

- [x] T001 Create settings.json configuration file in etl/seed/settings.json
- [x] T002 [P] Create test file for note_transform_lambda in etl/tests/test_note_transform_lambda.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core functions that MUST be complete before filter chain integration

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Implement load_settings() function in etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py
- [x] T004 Implement check_date_filter() function in etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Filter Notes by Start Date (Priority: P1) 🎯 MVP

**Goal**: Notes older than the configured start date are excluded from downstream processing (topic-detect-queue) while still being saved to the notes table.

**Independent Test**: Set start_millis to 2024-01-01, process notes from 2023 and 2024, verify only 2024+ notes reach topic-detect-queue.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T005 [P] [US1] Unit test for check_date_filter() - within range returns True in etl/tests/test_note_transform_lambda.py
- [x] T006 [P] [US1] Unit test for check_date_filter() - before start returns False in etl/tests/test_note_transform_lambda.py
- [x] T007 [P] [US1] Unit test for check_date_filter() - exact boundary (start_millis == created_at) returns True in etl/tests/test_note_transform_lambda.py
- [x] T008 [P] [US1] Unit test for check_date_filter() - Decimal type conversion works in etl/tests/test_note_transform_lambda.py

### Implementation for User Story 1

- [x] T009 [US1] Add created_at_millis to results dict in lambda_handler() in etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py
- [x] T010 [US1] Integrate check_date_filter() into filter chain after keyword filter in etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py
- [x] T011 [US1] Run tox in etl module to verify all tests pass

**Checkpoint**: At this point, date filtering should work with hardcoded values. User Story 1 is functional.

---

## Phase 4: User Story 2 - Configure Filters via Settings File (Priority: P2)

**Goal**: All filter settings (language, keyword, date) are loaded from unified settings.json file.

**Independent Test**: Modify settings.json with different values, verify Lambda uses those values for filtering.

### Tests for User Story 2

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T012 [P] [US2] Unit test for load_settings() - valid file loads correctly in etl/tests/test_note_transform_lambda.py
- [x] T013 [P] [US2] Unit test for load_settings() - missing file raises FileNotFoundError in etl/tests/test_note_transform_lambda.py
- [x] T014 [P] [US2] Unit test for load_settings() - missing start_millis raises ValueError in etl/tests/test_note_transform_lambda.py

### Implementation for User Story 2

- [x] T015 [US2] Call load_settings() at lambda_handler() start in etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py
- [x] T016 [US2] Replace hardcoded language filter with settings.filter.languages in etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py
- [x] T017 [US2] Replace load_keywords() call with settings.filter.keywords in etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py
- [x] T018 [US2] Use settings.filter.date_range.start_millis for date filter in etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py
- [x] T019 [US2] Run tox in etl module to verify all tests pass

**Checkpoint**: At this point, all filter configuration comes from settings.json. User Story 2 is functional.

---

## Phase 5: User Story 3 - Logging and Monitoring (Priority: P3)

**Goal**: All filtered notes are logged with skip reason, and result summary includes filter counts.

**Independent Test**: Process notes that trigger each filter type, verify logs contain note_id and skip reason.

### Tests for User Story 3

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T020 [P] [US3] Unit test for date filter skip logging - verifies log contains note_id and reason in etl/tests/test_note_transform_lambda.py

### Implementation for User Story 3

- [x] T021 [US3] Add date filter skip logging with note_id, created_at_millis, start_millis in etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py
- [x] T022 [US3] Add date_filtered_count to result summary in lambda_handler() response in etl/src/birdxplorer_etl/lib/lambda_handler/note_transform_lambda.py
- [x] T023 [US3] Run tox in etl module to verify all tests pass

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and code quality

- [x] T024 Run full tox suite (black, isort, pflake8, mypy, pytest) in etl/
- [x] T025 Verify quickstart.md steps work correctly
- [x] T026 Update etl/docs/issue-200-date-filter-design.md if implementation differs from design

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on T001 (settings.json exists)
- **User Stories (Phase 3-5)**: All depend on Foundational phase completion
  - User stories should proceed sequentially (P1 → P2 → P3) due to code integration
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2)
- **User Story 2 (P2)**: Depends on US1 completion (integrates settings loading)
- **User Story 3 (P3)**: Can start after Foundational but logically builds on US1/US2

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Implementation integrates into existing lambda_handler()
- Run tox after each story to validate

### Parallel Opportunities

Within each phase, tasks marked [P] can run in parallel:

- **Phase 1**: T001 and T002 can run in parallel
- **Phase 3 Tests**: T005, T006, T007, T008 can all run in parallel
- **Phase 4 Tests**: T012, T013, T014 can all run in parallel

---

## Parallel Example: User Story 1 Tests

```bash
# Launch all tests for User Story 1 together:
Task: "Unit test for check_date_filter() - within range returns True"
Task: "Unit test for check_date_filter() - before start returns False"
Task: "Unit test for check_date_filter() - exact boundary returns True"
Task: "Unit test for check_date_filter() - Decimal type conversion works"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T002)
2. Complete Phase 2: Foundational (T003-T004)
3. Complete Phase 3: User Story 1 (T005-T011)
4. **STOP and VALIDATE**: Run tox, test with real notes
5. Deploy if ready - date filtering is functional

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add User Story 1 → Test → Deploy (MVP - date filter works!)
3. Add User Story 2 → Test → Deploy (settings.json integration)
4. Add User Story 3 → Test → Deploy (enhanced logging)

---

## Notes

- All code changes are in a single file: `note_transform_lambda.py`
- Tests are in a single file: `test_note_transform_lambda.py`
- Configuration is in: `settings.json`
- Must pass tox (black, isort, pflake8, mypy, pytest) before PR
- Commit after each logical group of tasks
- Stop at any checkpoint to validate story independently
