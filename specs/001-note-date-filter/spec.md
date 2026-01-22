# Feature Specification: Note Date Filter

**Feature Branch**: `001-note-date-filter`
**Created**: 2026-01-21
**Status**: Draft
**Input**: User description: "note-transform-lambdaに日付フィルタリングを追加したい"
**Related Issue**: https://github.com/codeforjapan/BirdXplorer/issues/200

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Filter Notes by Date Range (Priority: P1)

システム管理者またはETLオペレーターとして、ノート変換処理において指定した日付範囲内のノートのみを下流処理（トピック検出、ポストルックアップ）の対象としたい。これにより、過去の古いノート（2022年など）に対する不要なAI処理をスキップし、対象期間のデータに集中できる。

**背景**: 現在、TSVファイルの最も古いデータから処理が開始されるため、古いノートに対して不要なAI処理（トピック検出等）が発生している。全ノートはデータベースに保存しつつ、下流処理は指定日付範囲内に絞り込む必要がある。

**Why this priority**: 日付フィルタリングは本機能の核心機能であり、これなしでは機能として成立しない。対象範囲外のノートへの不要な下流処理をスキップすることで、AI処理コストを削減し、データパイプラインの効率を向上させる。

**Independent Test**: 特定の日付範囲を設定し、その範囲内のノートのみが次の処理キュー（topic-detect-queue）に送信されることを確認することで、独立してテスト可能。

**Acceptance Scenarios**:

1. **Given** 日付フィルタとして「2024年1月1日〜2024年12月31日」が設定されている, **When** 2023年12月のノートが処理される, **Then** そのノートはnotesテーブルに保存されるが、topic-detect-queueには送信されない（範囲より前）
2. **Given** 日付フィルタとして「2024年1月1日〜2024年12月31日」が設定されている, **When** 2024年6月のノートが処理される, **Then** そのノートは通常通り処理され、条件を満たせばtopic-detect-queueに送信される（範囲内）
3. **Given** 日付フィルタとして「2024年1月1日〜2024年12月31日」が設定されている, **When** 2025年1月のノートが処理される, **Then** そのノートはnotesテーブルに保存されるが、topic-detect-queueには送信されない（範囲より後）
4. **Given** 日付フィルタとして「2024年1月1日〜（終了日未設定）」が設定されている, **When** 2026年1月の最新ノートが処理される, **Then** 開始日以降であり終了日未設定のため処理対象となる

---

### User Story 2 - Configure Filters via Settings File (Priority: P2)

システム管理者として、言語フィルタ、キーワードフィルタ、日付フィルタの設定を統合された設定ファイル（settings.json）で管理したい。これにより、フィルタ設定を一元管理でき、運用がシンプルになる。

**Why this priority**: 設定の統合管理は運用効率に直結するが、P1のコア機能が動作することが前提となる。また、既存のkeywords.jsonからの移行パスを提供する。

**Independent Test**: settings.jsonに異なる設定値を記述し、各フィルタが設定通りに動作することを確認。

**Acceptance Scenarios**:

1. **Given** settings.jsonに言語リスト、キーワードリスト、開始日が設定されている, **When** ノート変換処理が実行される, **Then** 全てのフィルタ設定が統合ファイルから読み込まれる
2. **Given** settings.jsonのstart_millisが未設定, **When** ノート変換処理が実行される, **Then** 処理がエラーとなり、必須項目の不足が報告される
3. **Given** settings.jsonが存在しない, **When** ノート変換処理が実行される, **Then** 処理がエラーとなり、設定ファイルの不足が報告される

---

### User Story 3 - Logging and Monitoring (Priority: P3)

システム管理者として、日付フィルタによってスキップされたノートの情報をログで確認したい。これにより、フィルタ設定が意図通りに動作しているかを監視できる。

**Why this priority**: 運用監視は重要だが、コア機能とは独立して追加可能な補助機能である。

**Independent Test**: 日付フィルタでスキップされたノートがログに記録されていることを確認。

**Acceptance Scenarios**:

1. **Given** 日付フィルタが有効, **When** フィルタ条件を満たさないノートが処理される, **Then** スキップされた理由（日付範囲外）と該当ノートIDがログに記録される
2. **Given** 日付フィルタが有効, **When** 処理が完了する, **Then** 各フィルタによりスキップされたノート数が結果サマリーに含まれる

---

### Edge Cases

- **境界日時のノート（開始日）**: フィルタの開始日時と同じ時刻に作成されたノートは処理対象に含まれる（start_millis <= created_at）
- **境界日時のノート（終了日）**: フィルタの終了日時と同じ時刻に作成されたノートは処理対象に含まれる（created_at <= end_millis）
- **end_millis未設定**: 終了日が未設定（null）の場合、開始日以降の全てのノートが処理対象となる
- **created_at_millisの型変換**: Decimal型で保存されている場合でも正しく数値比較できる
- **未来の開始日**: 開始日が未来の日付に設定された場合、全てのノートが日付フィルタでスキップされる
- **言語・キーワード・日付の順序**: フィルタは言語→キーワード→日付の順序で適用される（全てAND条件）

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: システムは、ノート変換処理において日付範囲に基づくフィルタリングを実行し、範囲外のノートを下流処理から除外しなければならない（MUST）
- **FR-002**: システムは、全ノートをrow_notes→notesテーブルに保存し、日付フィルタは下流処理（topic-detect-queue送信）にのみ適用しなければならない（MUST）
- **FR-003**: システムは、フィルタの開始日をミリ秒タイムスタンプ（start_millis）として必須項目で指定できなければならない（MUST）
- **FR-003a**: システムは、フィルタの終了日をミリ秒タイムスタンプ（end_millis）として任意項目で指定できなければならない（MUST）。未設定の場合は上限なしとして扱う
- **FR-004**: システムは、日付範囲内（start_millis <= created_at_millis <= end_millis、end_millis未設定時はstart_millis <= created_at_millis）の全てのノートを下流処理の対象としなければならない（MUST）
- **FR-005**: システムは、start_millisが未設定の場合、エラーを発生させ処理を開始しないようにしなければならない（MUST）
- **FR-006**: システムは、設定ファイル（settings.json）から言語フィルタ、キーワードフィルタ、日付フィルタの設定を統合的に読み込まなければならない（MUST）
- **FR-007**: システムは、フィルタによりスキップされたノートの情報（ノートID、スキップ理由）をログに記録しなければならない（MUST）
- **FR-008**: システムは、フィルタを言語→キーワード→日付の順序で適用しなければならない（MUST）

### Key Entities

- **Note（ノート）**: Community Notesのエントリ。主要属性として `note_id`（識別子）、`created_at_millis`（作成日時、ミリ秒タイムスタンプ）を持つ
- **Filter Configuration（フィルタ設定）**: settings.jsonで定義されるフィルタリング条件。言語リスト、キーワードリスト、開始日（start_millis必須）、終了日（end_millis任意）を含む

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 日付フィルタ設定後、開始日より前のノートがtopic-detect-queueに送信される割合が0%である
- **SC-002**: 全てのノートがnotesテーブルに保存される（日付フィルタによるデータ欠損0%）
- **SC-003**: 日付フィルタの追加による1ノートあたりの処理時間への影響が5%以内に収まる
- **SC-004**: 日付フィルタによりスキップされた全てのノートがログに記録される（記録漏れ0%）
- **SC-005**: start_millis未設定時に処理が確実にエラーとなる（誤動作0%）

## Assumptions

- ノートの作成日時（`created_at_millis`）はUTCのミリ秒タイムスタンプとして保存されている
- 既存のフィルタリング（言語フィルタ、キーワードフィルタ）との組み合わせはAND条件で動作する（すべての条件を満たす必要がある）
- 日付フィルタはtopic-detect-queue への送信前の判定に適用される（notesテーブルへの登録自体は行われる）
- 設定ファイルはseed/settings.jsonに配置される
- 既存のkeywords.jsonは後方互換性のため残すが、将来的にはsettings.jsonに完全移行する
- 終了日（end_millis）は任意項目であり、未設定の場合は上限なし（開始日以降の全てを対象）として動作する
