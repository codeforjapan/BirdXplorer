# Tasks: Graph API Backend

**Input**: Design documents from `/home/yu23ki14/cfj/BirdXplorer/specs/001-graph-api-backend/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/graphs-api.yml

**Tests**: Test tasks are included following test-first discipline per BirdXplorer Constitution Principle III.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4, US5, US6)
- Include exact file paths in descriptions

## Path Conventions

BirdXplorer uses multi-module architecture:
- **Common module**: `/home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/`
- **API module**: `/home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/`
- **Migration module**: `/home/yu23ki14/cfj/BirdXplorer/migrate/migration/versions/`
- **Tests**: `common/tests/` and `api/tests/`

---

## Phase 1: Setup (Database & Shared Infrastructure)

**Purpose**: Critical database indexes and shared utilities required by ALL graph endpoints

- [X] T001 Create Alembic migration for graph query indexes in /home/yu23ki14/cfj/BirdXplorer/migrate/migration/versions/add_graph_query_indexes.py
- [X] T002 Apply migration to add indexes: ix_notes_created_at, ix_notes_post_id, ix_posts_created_at, ix_notes_created_at_current_status, ix_posts_impression_count
- [X] T003 [P] Add PublicationStatus enum to /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py
- [X] T004 [P] Add GraphListResponse generic model to /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py
- [X] T005 [P] Implement _get_publication_status_case() helper function in /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/storage.py
- [X] T006 Update /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py __all__ export list with new models

**Checkpoint**: ✅ COMPLETE - Database indexed, shared models and utilities ready - user story implementation can begin

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story endpoints can function

**⚠️ CRITICAL**: No endpoint implementation can begin until this phase is complete

- [X] T007 Create new graphs router file /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py with FastAPI router initialization
- [X] T008 [P] Add PeriodType Literal type definition to /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py
- [X] T009 [P] Add StatusType Literal type definition to /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py
- [X] T010 [P] Implement _period_to_days() helper function in /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py
- [X] T011 [P] Implement _parse_month_range() helper function in /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py
- [X] T012 [P] Implement _fill_daily_gaps() helper function in /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/storage.py
- [X] T013 [P] Implement _fill_monthly_gaps() helper function in /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/storage.py
- [X] T014 [P] Implement get_graph_updated_at() method in /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/storage.py
- [X] T015 Register graphs router in /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/app.py with /api/v1 prefix

**Checkpoint**: ✅ COMPLETE - Foundation ready - all user story endpoints can now be implemented in parallel

---

## Phase 3: User Story 1 - View Daily Community Notes Creation Trends (Priority: P1) 🎯 MVP

**Goal**: Enable analysts to monitor daily community note creation patterns across 4 publication statuses

**Independent Test**: Request daily note counts for "1week" period and verify response contains correct status counts for each day with zero-filled gaps and updatedAt timestamp

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T016 [P] [US1] Unit test for get_daily_note_counts() storage method in /home/yu23ki14/cfj/BirdXplorer/common/tests/test_storage_graphs.py
- [X] T017 [P] [US1] Integration test for GET /api/v1/graphs/daily-notes endpoint in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [X] T018 [P] [US1] Test status filter parameter for daily-notes endpoint in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [X] T019 [P] [US1] Test date gap filling for daily-notes endpoint in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py

### Implementation for User Story 1

- [X] T020 [P] [US1] Add DailyNotesCreationDataItem model to /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py
- [X] T021 [US1] Implement get_daily_note_counts() method in /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/storage.py using date_trunc and CASE aggregation
- [X] T022 [US1] Implement GET /api/v1/graphs/daily-notes endpoint in /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py
- [X] T023 [US1] Add validation for period parameter (1week, 1month, 3months, 6months, 1year) in daily-notes endpoint
- [X] T024 [US1] Add error handling with HTTPException for invalid parameters in daily-notes endpoint
- [X] T025 [US1] Add endpoint description to /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/openapi_doc.py
- [X] T026 [US1] Run tox in common module to verify code quality gates
- [X] T027 [US1] Run tox in api module to verify code quality gates

**Checkpoint**: ✅ MVP COMPLETE - daily-notes endpoint fully functional and independently testable (tests pending database)

---

## Phase 4: User Story 2 - Analyze Post Volume Trends by Month (Priority: P2)

**Goal**: Enable administrators to analyze daily post counts across month ranges with note status filtering

**Independent Test**: Request daily post counts for range "2025-01_2025-03" and verify response contains daily data with correct status associations

### Tests for User Story 2

- [ ] T028 [P] [US2] Unit test for get_daily_post_counts() storage method in /home/yu23ki14/cfj/BirdXplorer/common/tests/test_storage_graphs.py
- [ ] T029 [P] [US2] Integration test for GET /api/v1/graphs/daily-posts endpoint in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T030 [P] [US2] Test range parameter validation (YYYY-MM_YYYY-MM format) in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T031 [P] [US2] Test posts without notes default to unpublished status in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py

### Implementation for User Story 2

- [ ] T032 [P] [US2] Add DailyPostCountDataItem model to /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py
- [ ] T033 [US2] Implement get_daily_post_counts() method in /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/storage.py with notes JOIN
- [ ] T034 [US2] Implement GET /api/v1/graphs/daily-posts endpoint in /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py
- [ ] T035 [US2] Add range parameter parsing and validation in daily-posts endpoint
- [ ] T036 [US2] Add error handling for invalid date ranges (start > end, exceeds max) in daily-posts endpoint
- [ ] T037 [US2] Add endpoint description to /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/openapi_doc.py
- [ ] T038 [US2] Run tox in common module to verify code quality gates
- [ ] T039 [US2] Run tox in api module to verify code quality gates

**Checkpoint**: User Stories 1 AND 2 complete - both endpoints independently functional

---

## Phase 5: User Story 3 - Track Monthly Note Publication Rates (Priority: P2)

**Goal**: Enable strategy teams to measure monthly publication rates (published / total notes)

**Independent Test**: Request annual data for range "2024-01_2024-12" and verify response includes publication rates with proper zero-division handling

### Tests for User Story 3

- [ ] T040 [P] [US3] Unit test for get_monthly_note_counts() storage method in /home/yu23ki14/cfj/BirdXplorer/common/tests/test_storage_graphs.py
- [ ] T041 [P] [US3] Integration test for GET /api/v1/graphs/notes-annual endpoint in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T042 [P] [US3] Test publication rate calculation (published / total) in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T043 [P] [US3] Test zero-division handling (0 notes returns 0.0 rate) in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py

### Implementation for User Story 3

- [ ] T044 [P] [US3] Add MonthlyNoteDataItem model to /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py
- [ ] T045 [US3] Implement get_monthly_note_counts() method in /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/storage.py with month truncation
- [ ] T046 [US3] Add publication rate calculation logic in get_monthly_note_counts() method
- [ ] T047 [US3] Implement GET /api/v1/graphs/notes-annual endpoint in /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py
- [ ] T048 [US3] Add range validation (max 24 months) in notes-annual endpoint
- [ ] T049 [US3] Add error handling for invalid month ranges in notes-annual endpoint
- [ ] T050 [US3] Add endpoint description to /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/openapi_doc.py
- [ ] T051 [US3] Run tox in common module to verify code quality gates
- [ ] T052 [US3] Run tox in api module to verify code quality gates

**Checkpoint**: User Stories 1, 2, AND 3 complete - all time-series endpoints functional

---

## Phase 6: User Story 4 - Evaluate Individual Note Performance (Priority: P3)

**Goal**: Enable researchers to analyze individual notes' effectiveness through ratings and impressions

**Independent Test**: Request note evaluation data for "1month" period with limit 50 and verify notes include ratings, impressions, and status sorted correctly

### Tests for User Story 4

- [ ] T053 [P] [US4] Unit test for get_note_evaluation_points() storage method in /home/yu23ki14/cfj/BirdXplorer/common/tests/test_storage_graphs.py
- [ ] T054 [P] [US4] Integration test for GET /api/v1/graphs/notes-evaluation endpoint in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T055 [P] [US4] Test sorting (impression DESC, helpful DESC) in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T056 [P] [US4] Test limit parameter (default 200, max 1000) in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T057 [P] [US4] Test NULL impression counts default to 0 in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py

### Implementation for User Story 4

- [ ] T058 [P] [US4] Add NoteEvaluationDataItem model to /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py
- [ ] T059 [US4] Implement get_note_evaluation_points() method in /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/storage.py with posts JOIN
- [ ] T060 [US4] Add sorting logic (impression_count DESC, helpful_count DESC) in get_note_evaluation_points() method
- [ ] T061 [US4] Add name generation from summary (first 200 chars) in get_note_evaluation_points() method
- [ ] T062 [US4] Implement GET /api/v1/graphs/notes-evaluation endpoint in /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py
- [ ] T063 [US4] Add limit parameter validation (1-1000 range) in notes-evaluation endpoint
- [ ] T064 [US4] Add error handling for invalid limits in notes-evaluation endpoint
- [ ] T065 [US4] Add endpoint description to /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/openapi_doc.py
- [ ] T066 [US4] Run tox in common module to verify code quality gates
- [ ] T067 [US4] Run tox in api module to verify code quality gates

**Checkpoint**: User Stories 1-4 complete - note evaluation analytics available

---

## Phase 7: User Story 5 - Compare Note Evaluation by Status (Priority: P3)

**Goal**: Enable moderators to compare notes across statuses with alternative sorting for moderation

**Independent Test**: Request note evaluation status data for "3months" period and verify notes sorted by helpful DESC, not-helpful ASC

### Tests for User Story 5

- [ ] T068 [P] [US5] Integration test for GET /api/v1/graphs/notes-evaluation-status endpoint in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T069 [P] [US5] Test sorting (helpful DESC, not_helpful ASC) in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T070 [P] [US5] Test default limit of 100 notes in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py

### Implementation for User Story 5

- [ ] T071 [US5] Implement GET /api/v1/graphs/notes-evaluation-status endpoint in /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py
- [ ] T072 [US5] Reuse get_note_evaluation_points() with different sort order (helpful DESC, not_helpful ASC)
- [ ] T073 [US5] Add default limit of 100 (no max override) in notes-evaluation-status endpoint
- [ ] T074 [US5] Add endpoint description to /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/openapi_doc.py
- [ ] T075 [US5] Run tox in api module to verify code quality gates

**Checkpoint**: User Stories 1-5 complete - moderation view available

---

## Phase 8: User Story 6 - Measure Post Influence and Reach (Priority: P3)

**Goal**: Enable marketing teams to analyze post engagement metrics and viral spread

**Independent Test**: Request post influence data for "1week" period and verify posts include engagement metrics and note status

### Tests for User Story 6

- [ ] T076 [P] [US6] Unit test for get_post_influence_points() storage method in /home/yu23ki14/cfj/BirdXplorer/common/tests/test_storage_graphs.py
- [ ] T077 [P] [US6] Integration test for GET /api/v1/graphs/post-influence endpoint in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T078 [P] [US6] Test sorting (impression_count DESC) in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py
- [ ] T079 [P] [US6] Test posts without notes default to unpublished status in /home/yu23ki14/cfj/BirdXplorer/api/tests/routers/test_graphs.py

### Implementation for User Story 6

- [ ] T080 [P] [US6] Add PostInfluenceDataItem model to /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py
- [ ] T081 [US6] Implement get_post_influence_points() method in /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/storage.py with notes JOIN
- [ ] T082 [US6] Add name generation from post text (first 200 chars) in get_post_influence_points() method
- [ ] T083 [US6] Add sorting logic (impression_count DESC) in get_post_influence_points() method
- [ ] T084 [US6] Implement GET /api/v1/graphs/post-influence endpoint in /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/routers/graphs.py
- [ ] T085 [US6] Add limit parameter validation (default 200, max 1000) in post-influence endpoint
- [ ] T086 [US6] Add error handling for invalid limits in post-influence endpoint
- [ ] T087 [US6] Add endpoint description to /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/openapi_doc.py
- [ ] T088 [US6] Run tox in common module to verify code quality gates
- [ ] T089 [US6] Run tox in api module to verify code quality gates

**Checkpoint**: ALL User Stories complete - all 6 graph endpoints functional

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and validation that affect multiple user stories

- [ ] T090 [P] Verify all models exported in /home/yu23ki14/cfj/BirdXplorer/common/birdxplorer_common/models.py __all__ list
- [ ] T091 [P] Run mypy --strict on common module to verify type safety
- [ ] T092 [P] Run mypy --strict on api module to verify type safety
- [ ] T093 [P] Verify all endpoints documented in /home/yu23ki14/cfj/BirdXplorer/api/birdxplorer_api/openapi_doc.py
- [ ] T094 Test all endpoints with curl using examples from /home/yu23ki14/cfj/BirdXplorer/specs/001-graph-api-backend/quickstart.md
- [ ] T095 Verify response times <3 seconds for all endpoints with sample data
- [ ] T096 [P] Format all code with black (120 char line length) in common and api modules
- [ ] T097 [P] Sort imports with isort (black profile) in common and api modules
- [ ] T098 Run pflake8 on common and api modules to verify linting
- [ ] T099 Run full tox suite in common module (final verification)
- [ ] T100 Run full tox suite in api module (final verification)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately. **CRITICAL: Migration MUST complete before any queries**
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-8)**: All depend on Foundational phase completion
  - User stories can proceed in parallel (if staffed) OR sequentially by priority
  - Priority order: US1 (P1) → US2 (P2) → US3 (P2) → US4 (P3) → US5 (P3) → US6 (P3)
- **Polish (Phase 9)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational - INDEPENDENT (no dependencies on other stories)
- **User Story 2 (P2)**: Can start after Foundational - INDEPENDENT (separate endpoint, separate models)
- **User Story 3 (P2)**: Can start after Foundational - INDEPENDENT (monthly vs daily aggregation)
- **User Story 4 (P3)**: Can start after Foundational - INDEPENDENT (individual note data)
- **User Story 5 (P3)**: Can start after US4 (reuses get_note_evaluation_points with different sort)
- **User Story 6 (P3)**: Can start after Foundational - INDEPENDENT (post-focused, not note-focused)

**Key Insight**: US1, US2, US3, US4, US6 are completely independent. US5 depends on US4 for reusing storage method.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD per Constitution)
- Models before storage methods (type definitions needed)
- Storage methods before endpoints (data layer before API layer)
- Core implementation before quality gates
- Story complete before moving to next priority

### Parallel Opportunities

**Setup Phase (Phase 1)**:
- T003, T004 (models) can run in parallel - different parts of models.py
- T005 (storage helper) parallel with models

**Foundational Phase (Phase 2)**:
- T008, T009 (type definitions) can run in parallel - same file, different sections
- T010, T011 (router helpers) can run in parallel - same file, different functions
- T012, T013, T014 (storage helpers) can run in parallel - different functions

**User Story Tests**:
- All tests within a story marked [P] can run in parallel (US1: T016-T019, US2: T028-T031, etc.)

**User Story Models**:
- All model additions marked [P] can run in parallel (US1: T020, US2: T032, US3: T044, US4: T058, US6: T080)

**Across User Stories** (if multiple developers):
- After Foundational completes, US1, US2, US3, US4, US6 can ALL proceed in parallel
- US5 must wait for US4 storage method completion

---

## Parallel Example: User Story 1

```bash
# Step 1: Launch all tests for User Story 1 together:
Task T016: "Unit test for get_daily_note_counts() storage method"
Task T017: "Integration test for GET /api/v1/graphs/daily-notes endpoint"
Task T018: "Test status filter parameter for daily-notes endpoint"
Task T019: "Test date gap filling for daily-notes endpoint"

# Step 2: After tests written and failing, launch model:
Task T020: "Add DailyNotesCreationDataItem model"

# Step 3: Implementation (sequential due to dependencies):
Task T021: "Implement get_daily_note_counts() method" (needs T020)
Task T022: "Implement GET /api/v1/graphs/daily-notes endpoint" (needs T021)
Task T023-T025: "Add validation, error handling, documentation"

# Step 4: Quality gates:
Task T026: "Run tox in common module"
Task T027: "Run tox in api module"
```

---

## Parallel Example: Multiple User Stories

```bash
# After Foundational Phase completes, these can run concurrently:

Developer A (US1 - Priority P1):
- Implements daily-notes endpoint (T016-T027)

Developer B (US2 - Priority P2):
- Implements daily-posts endpoint (T028-T039)

Developer C (US3 - Priority P2):
- Implements notes-annual endpoint (T040-T052)

Developer D (US6 - Priority P3):
- Implements post-influence endpoint (T076-T089)

# US4 and US5 can also run in parallel, but US5 waits for US4's storage method
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

**Fastest path to value**:
1. Complete Phase 1: Setup (T001-T006) - **~2 hours** (migration + models)
2. Complete Phase 2: Foundational (T007-T015) - **~3 hours** (router setup + helpers)
3. Complete Phase 3: User Story 1 (T016-T027) - **~4 hours** (tests + daily-notes endpoint)
4. **STOP and VALIDATE**: Test independently using quickstart.md
5. Deploy/demo MVP (single working analytics endpoint)

**Total MVP time**: ~9 hours (1-2 days)

### Incremental Delivery (Priority Order)

**Each story adds value without breaking previous stories**:
1. Setup + Foundational → **Foundation ready** (~5 hours)
2. Add US1 (P1) → Test independently → **Deploy MVP** (~4 hours)
3. Add US2 (P2) → Test independently → **Deploy v2** (~4 hours)
4. Add US3 (P2) → Test independently → **Deploy v3** (~4 hours)
5. Add US4 (P3) → Test independently → **Deploy v4** (~5 hours)
6. Add US5 (P3) → Test independently → **Deploy v5** (~3 hours)
7. Add US6 (P3) → Test independently → **Deploy v6** (~5 hours)
8. Polish (Phase 9) → **Production ready** (~3 hours)

**Total time (sequential)**: ~33 hours (4-5 days for one developer)

### Parallel Team Strategy

**With 3 developers after Foundational phase**:

1. **Team completes Setup + Foundational together** (~5 hours, day 1 morning)

2. **Parallel implementation** (day 1 afternoon - day 2):
   - **Developer A (critical path)**: US1 (P1) → US5 depends on US1? No, US5 depends on US4
   - **Developer B**: US2 (P2) → US3 (P2) (related: both post/note aggregations)
   - **Developer C**: US4 (P3) → US5 (P3) (US5 reuses US4 storage method)

3. **Developer D (if available)**: US6 (P3) in parallel

4. **Team reconvenes**: Polish phase together (~2 hours)

**Total time (parallel)**: ~12-15 hours (1.5-2 days for team of 3-4)

---

## Performance Notes

**From research.md**: Database indexes (T001-T002) are **CRITICAL**:
- Without indexes: 10-30+ seconds per query (FAILS performance target)
- With indexes: <500ms per query (MEETS <3 second target)

**Before starting implementation**:
1. Verify migration applied: `psql -c "\di notes*"`
2. Should see: ix_notes_created_at, ix_notes_post_id, ix_posts_created_at
3. If missing, queries will timeout and all tests will fail

---

## Testing Notes

**Test-First Discipline** (Constitution Principle III):
- Write tests BEFORE implementation for each user story
- Verify tests FAIL before writing code
- Tests should pass after implementation
- Run tox after each story to verify quality gates

**Test Coverage**:
- Unit tests: Storage methods in common/tests/test_storage_graphs.py
- Integration tests: Endpoints in api/tests/routers/test_graphs.py
- Each test file covers all related functionality for easier maintenance

---

## Quality Gates

**After each user story** (T026-T027, T038-T039, etc.):
1. **Format**: black + isort (120 char lines, black profile)
2. **Lint**: pflake8 (max-line-length=120, extend-ignore=E203,E701)
3. **Type**: mypy --strict (Python 3.10, strict mode, Pydantic plugin)
4. **Tests**: pytest with coverage

**Command**: `tox` (runs all gates)

**Failure = STOP**: Fix issues before proceeding to next story

---

## Notes

- **[P] tasks** = different files or independent functions, no shared state, can run in parallel
- **[Story] label** = maps task to specific user story for traceability and MVP scoping
- **Each user story** = independently completable and testable (no cross-story blocking)
- **Database migration** = MUST complete before any storage/endpoint work (T001-T002 blocking)
- **Commit frequency**: After each task or logical group (T020-T021, T022-T025, etc.)
- **Stop at checkpoints**: Validate story independently before proceeding
- **Avoid**: Cross-story dependencies, same file conflicts during parallel work

---

## Task Summary

- **Total Tasks**: 100
- **Setup Phase**: 6 tasks
- **Foundational Phase**: 9 tasks
- **User Story 1** (P1): 12 tasks (4 tests + 8 implementation)
- **User Story 2** (P2): 12 tasks (4 tests + 8 implementation)
- **User Story 3** (P2): 13 tasks (4 tests + 9 implementation)
- **User Story 4** (P3): 15 tasks (5 tests + 10 implementation)
- **User Story 5** (P3): 8 tasks (3 tests + 5 implementation)
- **User Story 6** (P3): 14 tasks (4 tests + 10 implementation)
- **Polish Phase**: 11 tasks (quality verification)

**Parallel Opportunities**: 45 tasks marked [P] can run in parallel (45% of total)

**MVP Scope**: Phases 1-3 (27 tasks) = Working daily-notes endpoint (~9 hours)

**Format Validation**: ✅ All tasks follow checklist format: `- [ ] [ID] [P?] [Story?] Description with file path`
