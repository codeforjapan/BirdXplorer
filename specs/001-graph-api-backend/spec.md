# Feature Specification: Graph API Backend

**Feature Branch**: `001-graph-api-backend`
**Created**: 2026-01-13
**Status**: Draft
**Input**: User description: "グラフAPIバックエンド実装: 6種類のグラフエンドポイント追加(DailyNotesCreationChart, DailyPostCountChart, NotesAnnualChartSection, NotesEvaluationChartSection, NotesEvaluationStatusChart, PostInfluenceChart)"

## Clarifications

### Session 2026-01-13

- Q: Should these graph API endpoints require authentication, and if so, what level of access control is needed? → A: Public endpoints - no authentication required (analytics are open to all)
- Q: What format should error responses follow when validation fails or errors occur? → A: Match existing BirdXplorer API error format; if ambiguous, use standard JSON: {"error": "error_code", "message": "description"}
- Q: Should the public graph API endpoints implement rate limiting to prevent abuse? → A: No rate limiting - rely on query optimization and infrastructure scaling
- Q: What observability requirements should be in place for monitoring these graph API endpoints? → A: Minimal - only log errors and exceptions, no success metrics
- Q: What is the strategy for API versioning and handling breaking changes to these graph endpoints? → A: No versioning strategy needed - breaking changes acceptable, update in place

## User Scenarios & Testing

### User Story 1 - View Daily Community Notes Creation Trends (Priority: P1)

Analysts need to monitor community note creation patterns over time to understand engagement levels and identify unusual activity patterns. This visualization shows the daily distribution of notes across four publication statuses.

**Why this priority**: This is the most fundamental metric for understanding platform health and community engagement. It provides immediate visibility into whether the community note system is functioning and being used.

**Independent Test**: Can be fully tested by requesting daily note counts for a 1-week period and verifying that the response contains correctly categorized notes by status (published, evaluating, unpublished, temporarilyPublished) for each day, delivering a complete picture of note creation activity.

**Acceptance Scenarios**:

1. **Given** the system has community notes created over the past week, **When** an analyst requests daily note counts for "1week" period, **Then** the system returns an array of daily data points with counts for each of the 4 publication statuses and the last update timestamp
2. **Given** the analyst wants to focus on published notes only, **When** they request daily note counts with status filter "published", **Then** the system returns daily counts showing only published notes while other statuses are zero or excluded
3. **Given** there are gaps in data (days with no notes), **When** requesting a date range, **Then** the system fills missing days with zero counts to ensure continuous visualization

---

### User Story 2 - Analyze Post Volume Trends by Month (Priority: P2)

Administrators need to understand post volume patterns across specific months to correlate with external events, campaigns, or platform changes. This view shows daily post counts within a selected month range, filtered by the associated notes' publication status.

**Why this priority**: Essential for operational analytics and understanding how post volume relates to community note activity, but less critical than basic note monitoring.

**Independent Test**: Can be fully tested by requesting daily post counts for a specific month range (e.g., "2025-01_2025-03") and verifying that each day within the range has post counts, optionally filtered by note status, delivering insights into post-to-note relationships.

**Acceptance Scenarios**:

1. **Given** posts exist across multiple months, **When** an administrator requests post counts for range "2025-01_2025-03", **Then** the system returns daily post counts for January through March with associated note status information
2. **Given** the administrator wants to see posts with published notes only, **When** they apply status filter "published", **Then** the system returns daily post counts showing only posts that have published community notes
3. **Given** a requested month range spans up to 3 months, **When** requesting data, **Then** the system processes all days in the range and returns complete daily data including days with zero posts

---

### User Story 3 - Track Monthly Note Publication Rates (Priority: P2)

Strategy teams need to measure the effectiveness of the community note system by tracking monthly publication rates - what percentage of notes progress from evaluation to published status.

**Why this priority**: Critical for measuring system effectiveness and community quality, but requires data aggregation from Story 1, making it a natural second priority.

**Independent Test**: Can be fully tested by requesting monthly note aggregates for a year-long range and verifying the response includes total counts by status plus calculated publication rate (published / total notes) for each month, delivering a health scorecard.

**Acceptance Scenarios**:

1. **Given** notes exist across 12 months, **When** a strategist requests annual note data for range "2024-01_2024-12", **Then** the system returns 12 monthly data points each containing counts for all 4 statuses and a calculated publication rate
2. **Given** a month has 100 published notes and 400 total notes, **When** calculating publication rate, **Then** the system returns publication_rate as 0.25 (25%)
3. **Given** a month has zero notes, **When** calculating publication rate, **Then** the system returns publication_rate as 0 to avoid division errors

---

### User Story 4 - Evaluate Individual Note Performance (Priority: P3)

Researchers need to analyze individual community notes' effectiveness by examining their helpful/not-helpful ratings and reach (impressions) to identify patterns in successful notes.

**Why this priority**: Provides deeper analytical insights but depends on the foundation of Stories 1-3 for context.

**Independent Test**: Can be fully tested by requesting note evaluation data for a 1-month period with a limit of 50 notes and verifying each note includes its ratings, impression counts, and current status, delivering a dataset for quality analysis.

**Acceptance Scenarios**:

1. **Given** community notes exist with varying helpful/not-helpful counts, **When** a researcher requests note evaluation data for "1month" period, **Then** the system returns up to 200 notes (default limit) ordered by impression count and helpful count, each with full rating details
2. **Given** the researcher wants to focus on highly visible notes, **When** they set limit to 50, **Then** the system returns only the top 50 notes by impression count and helpful count
3. **Given** notes have associated posts with impression data, **When** retrieving note evaluation data, **Then** each note includes the impression count from its associated post (or 0 if no post link)

---

### User Story 5 - Compare Note Evaluation by Status (Priority: P3)

Moderators need to compare notes across different publication statuses to understand evaluation patterns and identify notes that may need review or reconsideration.

**Why this priority**: A specialized view of Story 4 data, useful for moderation but not essential for general analytics.

**Independent Test**: Can be fully tested by requesting note evaluation status data for a 3-month period and verifying the response returns notes grouped or sortable by status with consistent evaluation metrics, delivering a moderation dashboard view.

**Acceptance Scenarios**:

1. **Given** notes across all 4 publication statuses exist, **When** a moderator requests note evaluation status data for "3months", **Then** the system returns up to 100 notes (default) sorted by helpful count (descending) and not-helpful count (ascending)
2. **Given** the moderator wants to review all statuses, **When** they set status filter to "all", **Then** the system includes notes from published, evaluating, unpublished, and temporarilyPublished statuses
3. **Given** the sort order prioritizes high helpful and low not-helpful counts, **When** retrieving data, **Then** notes with more helpful ratings and fewer not-helpful ratings appear first

---

### User Story 6 - Measure Post Influence and Reach (Priority: P3)

Marketing and community teams need to understand which posts have the most influence through reposts, likes, and impressions, particularly in relation to their community note status.

**Why this priority**: Valuable for understanding post virality and community note correlation, but peripheral to core note system monitoring.

**Independent Test**: Can be fully tested by requesting post influence data for a 1-week period and verifying each post includes engagement metrics (repost_count, like_count, impression_count) and associated note status, delivering an engagement leaderboard.

**Acceptance Scenarios**:

1. **Given** posts with varying engagement levels exist, **When** a team member requests post influence data for "1week" period, **Then** the system returns up to 200 posts (default limit) ordered by impression count with full engagement metrics
2. **Given** posts may or may not have associated notes, **When** retrieving influence data, **Then** posts without notes are assigned "unpublished" status as a default
3. **Given** the request specifies limit of 100, **When** retrieving data, **Then** the system returns only the top 100 posts by impression count

---

### Edge Cases

- **Date range exceeds maximum**: System returns 400 error when range spans more than maximum allowed period (1 year for daily-notes, 24 months for notes-annual)
- **Future or pre-launch dates**: System returns 400 error for future dates; for dates before platform launch, returns empty data array (not an error)
- **No data for period**: System returns HTTP 200 with empty data array (not an error condition)
- **Notes without posts**: Status calculation treats orphaned notes as having NULL impression counts (converted to 0 per FR-023)
- **NULL or negative impression counts**: NULL treated as 0; negative values treated as 0 to prevent invalid analytics
- **Invalid status filter**: System returns 400 error with message indicating valid status values
- **Limit exceeds maximum**: System returns 400 error when limit parameter exceeds 1000
- **Timezone handling**: All timestamps stored and returned in UTC; clients responsible for timezone conversion
- **Status transitions during aggregation**: Uses snapshot consistency - status at query execution time determines categorization
- **Concurrent expensive queries**: System handles via read-only query optimization and infrastructure scaling; no rate limiting implemented (per FR-033)

## Requirements

### Functional Requirements

- **FR-001**: System MUST provide endpoint `/api/v1/graphs/daily-notes` accepting period parameter ("1week", "1month", "3months", "6months", "1year") and optional status filter
- **FR-002**: System MUST provide endpoint `/api/v1/graphs/daily-posts` accepting range parameter (format "YYYY-MM_YYYY-MM") and optional status filter
- **FR-003**: System MUST provide endpoint `/api/v1/graphs/notes-annual` accepting range parameter (max 24 months) and optional status filter
- **FR-004**: System MUST provide endpoint `/api/v1/graphs/notes-evaluation` accepting period parameter, optional status filter, and optional limit (default 200, max 1000)
- **FR-005**: System MUST provide endpoint `/api/v1/graphs/notes-evaluation-status` accepting period parameter and optional status filter with default limit of 100
- **FR-006**: System MUST provide endpoint `/api/v1/graphs/post-influence` accepting period parameter, optional status filter, and optional limit (default 200, max 1000)
- **FR-007**: System MUST calculate four distinct publication statuses from existing data:
  - "published": current_status = CURRENTLY_RATED_HELPFUL
  - "temporarilyPublished": has_been_helpfuled = true AND current_status IN (NEEDS_MORE_RATINGS, CURRENTLY_RATED_NOT_HELPFUL)
  - "evaluating": current_status = NEEDS_MORE_RATINGS AND has_been_helpfuled = false
  - "unpublished": all other cases
- **FR-008**: System MUST aggregate daily note counts by publication status for the requested period
- **FR-009**: System MUST aggregate daily post counts and join with note status information for the requested month range
- **FR-010**: System MUST calculate monthly publication rate as: published_count / (total_notes) for annual charts
- **FR-011**: System MUST retrieve individual note metrics including helpful_count, not_helpful_count, and impression_count from associated posts
- **FR-012**: System MUST join posts with notes to assign publication status, defaulting to "unpublished" when no note exists
- **FR-013**: System MUST sort note evaluation data by impression_count DESC, then helpful_count DESC
- **FR-014**: System MUST sort note evaluation status data by helpful_count DESC, then not_helpful_count ASC
- **FR-015**: System MUST sort post influence data by impression_count DESC
- **FR-016**: System MUST fill missing dates with zero counts to ensure continuous time series data
- **FR-017**: System MUST validate period parameter values and reject invalid formats
- **FR-018**: System MUST validate range parameter format (YYYY-MM_YYYY-MM) and ensure start month is before or equal to end month
- **FR-019**: System MUST enforce maximum range constraints (1 year for daily-notes, 24 months for notes-annual)
- **FR-020**: System MUST enforce limit parameter constraints (max 1000)
- **FR-021**: System MUST include updatedAt timestamp in all responses formatted as "YYYY-MM-DD" in UTC
- **FR-022**: System MUST derive updatedAt from MAX(created_at) of the relevant table (notes or posts)
- **FR-023**: System MUST handle NULL impression counts by treating them as 0
- **FR-024**: System MUST handle division by zero in publication rate calculation by returning 0
- **FR-025**: System MUST filter aggregations by status when status parameter is provided and not "all"
- **FR-026**: All responses MUST follow format: { "data": [...], "updatedAt": "YYYY-MM-DD" }
- **FR-027**: System MUST return empty array for data when no records match the query criteria
- **FR-028**: System MUST use existing database tables (notes, posts) without requiring new tables
- **FR-029**: System MUST leverage existing columns (current_status, has_been_helpfuled, created_at, updated_at, post_id, impression_count, repost_count, like_count, helpful_count, not_helpful_count)
- **FR-030**: System MUST support concurrent read requests without blocking
- **FR-031**: All graph API endpoints MUST be publicly accessible without authentication or authorization requirements
- **FR-032**: Error responses MUST follow the existing BirdXplorer API error format; if no established format exists, use JSON structure with "error" and "message" fields accompanied by appropriate HTTP status codes (400 for validation errors, 404 for not found, 500 for server errors)
- **FR-033**: System MUST NOT implement rate limiting on graph API endpoints; performance protection relies on query optimization and infrastructure scaling
- **FR-034**: System MUST log errors and exceptions for graph API endpoints; success requests do not require logging or metrics collection
- **FR-035**: Graph API endpoints MAY be modified with breaking changes without versioning constraints; no backwards compatibility guarantees are required

### Key Entities

- **Community Note**: A user-contributed annotation on a post containing evaluation status (current_status), historical publication status (has_been_helpfuled), creation timestamp, rating counts (helpful, not-helpful), and association to a post. The derived publication status ("published", "temporarilyPublished", "evaluating", "unpublished") is calculated from current_status and has_been_helpfuled.

- **Post**: A social media post with engagement metrics (repost_count, like_count, impression_count), creation timestamp, and zero-to-many associated community notes. The post's effective note status is derived from its associated notes.

- **Publication Status**: A derived categorical value (not stored) representing the current visibility state of a community note, calculated using business logic from current_status and has_been_helpfuled fields.

- **Time Period**: A relative duration specification ("1week", "1month", "3months", "6months", "1year") used to filter data based on creation timestamps.

- **Date Range**: An absolute month-based specification ("YYYY-MM_YYYY-MM") defining inclusive start and end boundaries for monthly aggregations.

- **Note Evaluation Metrics**: A composite of rating counts (helpful_count, not_helpful_count) and reach (impression_count from associated post) representing a note's effectiveness.

- **Post Influence Metrics**: A composite of engagement indicators (repost_count, like_count, impression_count) representing a post's reach and impact.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Analysts can retrieve daily note creation trends for any relative period (1 week to 1 year) within 3 seconds
- **SC-002**: Administrators can view daily post counts for up to 3 months of data within 3 seconds
- **SC-003**: All graph endpoints return correctly formatted time series data with zero-filled gaps for missing dates
- **SC-004**: Note evaluation queries return top 200 notes by visibility and rating within 3 seconds
- **SC-005**: Post influence queries return top 200 posts by engagement within 3 seconds
- **SC-006**: Publication rate calculations are mathematically accurate (published/total) with proper zero-division handling
- **SC-007**: All status calculations correctly categorize notes into exactly one of four statuses based on defined logic
- **SC-008**: System handles 100 concurrent read requests to graph endpoints without response time degradation beyond 5 seconds
- **SC-009**: All graph responses include accurate updatedAt timestamp reflecting the most recent data change
- **SC-010**: Status filtering reduces result sets correctly (e.g., "published" filter returns only published notes)
- **SC-011**: Limit parameters correctly restrict result set size to requested maximum
- **SC-012**: Invalid query parameters return appropriate error responses with clear messaging
- **SC-013**: All endpoints return consistent response structure with "data" array and "updatedAt" field
- **SC-014**: Queries spanning maximum allowed ranges (1 year daily, 24 months monthly) complete within 5 seconds
- **SC-015**: Zero data scenarios return empty arrays rather than errors, maintaining API contract

## Assumptions

- Database contains sufficient historical data (at least 3 months) for meaningful trend analysis
- Existing database indexes on created_at and post_id columns provide adequate query performance
- UTC timezone is standard for all timestamps in the database
- Current_status values are limited to predefined set (CURRENTLY_RATED_HELPFUL, NEEDS_MORE_RATINGS, CURRENTLY_RATED_NOT_HELPFUL)
- Has_been_helpfuled is a boolean field that reliably tracks historical publication state
- Posts and notes have proper foreign key relationships via post_id
- Impression counts represent cumulative views and are non-decreasing over time
- API consumers can handle zero-filled time series data for visualization
- The existing ETL process maintains data quality for current_status and has_been_helpfuled fields
- No real-time updates are required; eventual consistency is acceptable
- Graph data updates align with ETL batch processing schedules
- English and Japanese language support is sufficient for note names/summaries in responses
- HTTP 200 status code is appropriate for successful requests even when data array is empty
- Query performance for aggregations across millions of records is achievable with proper indexing
- Status filter values are case-sensitive and must match exactly ("published", not "Published")
- All graph analytics data is considered public information requiring no authentication or access control
- Infrastructure has sufficient capacity to handle unconstrained public access through query optimization and horizontal scaling without rate limiting
- Minimal observability is sufficient; detailed usage metrics and request logging are not required for successful requests
- API consumers accept that breaking changes may occur without versioning; no backwards compatibility contract is established
