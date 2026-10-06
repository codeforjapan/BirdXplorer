# 月次レポート自動生成パイプライン 実装計画

> **エージェント向け:** 必須サブスキル: superpowers:subagent-driven-development（推奨）または superpowers:executing-plans を使用して、タスクごとに実装してください。ステップはチェックボックス (`- [ ]`) 形式で進捗を管理します。

**目標:** BirdXplorer の RDS から月次日本語ノートを抽出し、kouchou-ai で分析・静的HTML生成を行い、BirdXplorer_Viewer リポに自動 PR を作成するパイプラインを構築する。

**アーキテクチャ:** Python orchestrator スクリプトが ECS Fargate タスクのメインコンテナとして動作し、サイドカーの kouchou-ai API と static-site-builder を `localhost` 経由で呼び出す。EventBridge で毎月3日に自動実行。

**技術スタック:** Python 3.10+, SQLAlchemy, requests, psycopg2, Docker, AWS CDK (TypeScript), ECS Fargate, EventBridge

**設計書:** `docs/superpowers/specs/2026-04-03-report-automation-design.md`

---

## ファイルマップ

### BirdXplorer/etl（orchestrator スクリプト）

| ファイル | 責務 |
|---------|------|
| `src/birdxplorer_etl/scripts/__init__.py` | パッケージ初期化 |
| `src/birdxplorer_etl/scripts/report_db.py` | RDS から日本語ノートを抽出して CSV 生成 |
| `src/birdxplorer_etl/scripts/report_kouchou.py` | kouchou-ai API クライアント（分析実行・ステータスポーリング・静的ビルド取得） |
| `src/birdxplorer_etl/scripts/report_github.py` | GitHub API クライアント（ブランチ作成・ファイルコミット・PR 作成） |
| `src/birdxplorer_etl/scripts/report_templates.py` | reports.ts / _index.tsx の更新テンプレート生成 |
| `src/birdxplorer_etl/scripts/report_generator.py` | メインオーケストレーター（CLI エントリポイント） |
| `tests/test_report_db.py` | report_db のテスト |
| `tests/test_report_kouchou.py` | report_kouchou のテスト |
| `tests/test_report_github.py` | report_github のテスト |
| `tests/test_report_templates.py` | report_templates のテスト |
| `Dockerfile.report-generator` | orchestrator 用 Docker イメージ |

### BirdXplorer-cdk（インフラ）

| ファイル | 変更内容 |
|---------|---------|
| `lib/bird_xplorer-stack.ts` | ReportGenerator ECS タスク定義 + EventBridge ルール追加 |
| `lib/config.ts` | EcsConfig に新リポジトリ名を追加 |
| `config/dev.json` | ECR リポジトリ名追加 |
| `config/prd.json` | ECR リポジトリ名追加 |

---

### タスク 1: report_db — DB 抽出モジュール

**ファイル:**
- 作成: `src/birdxplorer_etl/scripts/__init__.py`
- 作成: `src/birdxplorer_etl/scripts/report_db.py`
- 作成: `tests/test_report_db.py`

- [ ] **ステップ 1: テストを書く**

```python
# tests/test_report_db.py
import csv
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


class TestExtractNotes:
    @patch("birdxplorer_etl.scripts.report_db.init_postgresql")
    def test_extracts_japanese_notes_for_target_month(self, mock_init):
        from birdxplorer_etl.scripts.report_db import extract_notes

        mock_session = MagicMock()
        mock_init.return_value = mock_session

        mock_note_1 = MagicMock()
        mock_note_1.note_id = "note_001"
        mock_note_1.summary = "テスト要約1"
        mock_note_1.created_at = 1740000000000

        mock_note_2 = MagicMock()
        mock_note_2.note_id = "note_002"
        mock_note_2.summary = "テスト要約2"
        mock_note_2.created_at = 1740100000000

        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            mock_note_1,
            mock_note_2,
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            output_path = f.name

        try:
            result = extract_notes(
                target_year=2025,
                target_month=2,
                output_path=output_path,
            )

            assert result == 2

            with open(output_path, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 2
                assert rows[0]["comment-id"] == "note_001"
                assert rows[0]["comment-body"] == "テスト要約1"
        finally:
            os.unlink(output_path)

    @patch("birdxplorer_etl.scripts.report_db.init_postgresql")
    def test_returns_zero_when_no_notes(self, mock_init):
        from birdxplorer_etl.scripts.report_db import extract_notes

        mock_session = MagicMock()
        mock_init.return_value = mock_session
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            output_path = f.name

        try:
            result = extract_notes(target_year=2025, target_month=2, output_path=output_path)
            assert result == 0
        finally:
            os.unlink(output_path)


class TestCalculateDateRange:
    def test_february_2026(self):
        from birdxplorer_etl.scripts.report_db import calculate_date_range

        start_ms, end_ms = calculate_date_range(2026, 2)
        # 2026-02-01 00:00:00 UTC = 1738368000000
        # 2026-03-01 00:00:00 UTC = 1740787200000
        assert start_ms == 1738368000000
        assert end_ms == 1740787200000

    def test_december_wraps_to_next_year(self):
        from birdxplorer_etl.scripts.report_db import calculate_date_range

        start_ms, end_ms = calculate_date_range(2025, 12)
        # 2025-12-01 → 2026-01-01
        assert start_ms < end_ms
```

- [ ] **ステップ 2: テストが失敗することを確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
python -m pytest tests/test_report_db.py -v
```

- [ ] **ステップ 3: 実装**

```python
# src/birdxplorer_etl/scripts/__init__.py
# (空ファイル)
```

```python
# src/birdxplorer_etl/scripts/report_db.py
import csv
import logging
from calendar import monthrange
from datetime import datetime, timezone

from sqlalchemy import and_

from birdxplorer_common.storage import NoteRecord
from birdxplorer_etl.lib.sqlite.init import init_postgresql

logger = logging.getLogger(__name__)


def calculate_date_range(year: int, month: int) -> tuple[int, int]:
    """対象年月の開始・終了タイムスタンプ（ミリ秒）を返す"""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def extract_notes(
    target_year: int,
    target_month: int,
    output_path: str,
    db_host: str | None = None,
    db_port: str | None = None,
    db_user: str | None = None,
    db_pass: str | None = None,
    db_name: str | None = None,
) -> int:
    """RDS から日本語ノートを抽出して CSV に書き出す。件数を返す。"""
    import os

    if db_host:
        os.environ["DB_HOST"] = db_host
    if db_port:
        os.environ["DB_PORT"] = db_port
    if db_user:
        os.environ["DB_USER"] = db_user
    if db_pass:
        os.environ["DB_PASS"] = db_pass
    if db_name:
        os.environ["DB_NAME"] = db_name

    start_millis, end_millis = calculate_date_range(target_year, target_month)
    logger.info(f"Extracting notes: {target_year}/{target_month} ({start_millis} - {end_millis})")

    session = init_postgresql()
    try:
        notes = (
            session.query(NoteRecord)
            .filter(
                and_(
                    NoteRecord.language == "ja",
                    NoteRecord.created_at >= start_millis,
                    NoteRecord.created_at < end_millis,
                )
            )
            .order_by(NoteRecord.created_at)
            .all()
        )

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["comment-id", "comment-body"])
            writer.writeheader()
            for note in notes:
                writer.writerow(
                    {
                        "comment-id": str(note.note_id),
                        "comment-body": str(note.summary).replace("\n", " "),
                    }
                )

        logger.info(f"Extracted {len(notes)} notes to {output_path}")
        return len(notes)
    finally:
        session.close()
```

- [ ] **ステップ 4: テストが通ることを確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
python -m pytest tests/test_report_db.py -v
```

- [ ] **ステップ 5: コミット**

```bash
git add src/birdxplorer_etl/scripts/__init__.py src/birdxplorer_etl/scripts/report_db.py tests/test_report_db.py
git commit -m "feat: add report_db module for monthly notes extraction"
```

---

### タスク 2: report_kouchou — kouchou-ai API クライアント

**ファイル:**
- 作成: `src/birdxplorer_etl/scripts/report_kouchou.py`
- 作成: `tests/test_report_kouchou.py`

- [ ] **ステップ 1: テストを書く**

```python
# tests/test_report_kouchou.py
import json
from unittest.mock import MagicMock, patch, mock_open

import pytest


class TestCreateReport:
    @patch("birdxplorer_etl.scripts.report_kouchou.requests.post")
    def test_creates_report_and_returns_slug(self, mock_post):
        from birdxplorer_etl.scripts.report_kouchou import create_report

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"slug": "test-slug-123"}
        mock_post.return_value = mock_response

        slug = create_report(
            api_url="http://localhost:8000",
            admin_api_key="admin",
            csv_path="/tmp/test.csv",
            title="2026年 3月レポート",
        )

        assert slug == "test-slug-123"
        mock_post.assert_called_once()


class TestWaitForCompletion:
    @patch("birdxplorer_etl.scripts.report_kouchou.requests.get")
    @patch("birdxplorer_etl.scripts.report_kouchou.time.sleep")
    def test_returns_when_status_is_completed(self, mock_sleep, mock_get):
        from birdxplorer_etl.scripts.report_kouchou import wait_for_completion

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "completed"}
        mock_get.return_value = mock_response

        wait_for_completion(
            api_url="http://localhost:8000",
            admin_api_key="admin",
            slug="test-slug",
            timeout_minutes=60,
        )

        mock_sleep.assert_not_called()

    @patch("birdxplorer_etl.scripts.report_kouchou.requests.get")
    @patch("birdxplorer_etl.scripts.report_kouchou.time.sleep")
    def test_raises_on_timeout(self, mock_sleep, mock_get):
        from birdxplorer_etl.scripts.report_kouchou import wait_for_completion

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "running", "current_step": "extraction"}
        mock_get.return_value = mock_response

        with pytest.raises(TimeoutError):
            wait_for_completion(
                api_url="http://localhost:8000",
                admin_api_key="admin",
                slug="test-slug",
                timeout_minutes=0,
            )


class TestDownloadStaticBuild:
    @patch("birdxplorer_etl.scripts.report_kouchou.requests.post")
    def test_downloads_zip(self, mock_post):
        from birdxplorer_etl.scripts.report_kouchou import download_static_build

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"PK\x03\x04fake_zip_content"
        mock_post.return_value = mock_response

        output_path = "/tmp/test_output.zip"
        with patch("builtins.open", mock_open()) as mock_file:
            download_static_build(
                builder_url="http://localhost:3200",
                slug="test-slug",
                output_path=output_path,
            )
            mock_file.assert_called_once_with(output_path, "wb")
```

- [ ] **ステップ 2: テストが失敗することを確認**

```bash
python -m pytest tests/test_report_kouchou.py -v
```

- [ ] **ステップ 3: 実装**

```python
# src/birdxplorer_etl/scripts/report_kouchou.py
import csv
import logging
import time

import requests

logger = logging.getLogger(__name__)

DEFAULT_PROMPTS = {
    "extraction": (
        "あなたは専門的なリサーチアシスタントです。与えられたテキストから、意見を抽出して整理してください。\n\n"
        "# 指示\n"
        "* 入出力の例に記載したような形式で文字列のリストを返してください\n"
        "  * 必要な場合は2つの別個の意見に分割してください。多くの場合は1つの議論にまとめる方が望ましいです。\n"
        "* 整理した意見は日本語で出力してください\n\n"
        '## 入出力の例\n/human\n\nAIテクノロジーは、そのライフサイクル全体における環境負荷を削減することに焦点を当てて開発されるべきです。\n\n/ai\n\n{\n  "extractedOpinionList": [\n    "AIテクノロジーは、そのライフサイクル全体における環境負荷を削減することに焦点を当てて開発されるべきです。"\n  ]\n}\n\n/human\n\nAIの能力、限界、倫理的考慮事項について、市民を教育する必要がある。また、教育できる人材を養成する必要がある。\n\n/ai\n\n{\n  "extractedOpinionList": [\n    "AIの能力、限界、倫理的考慮事項について、市民を教育すべき",\n    "AIに関する教育をできる人材を養成すべき"\n  ]\n}\n\n/human\n\nAIはエネルギーグリッドを最適化し、無駄や炭素排出を削減できます。\n\n/ai\n\n{\n  "extractedOpinionList": [\n    "AIはエネルギーグリッドを最適化して炭素排出を削減できる"\n  ]\n}\n'
    ),
}


def create_report(
    api_url: str,
    admin_api_key: str,
    csv_path: str,
    title: str,
    model: str = "gpt-4o-mini",
    cluster_nums: list[int] | None = None,
    workers: int = 30,
) -> str:
    """kouchou-ai API でレポートを作成し、slug を返す"""
    if cluster_nums is None:
        cluster_nums = [20, 100]

    comments = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            comments.append({"id": row["comment-id"], "comment": row["comment-body"]})

    logger.info(f"Creating report '{title}' with {len(comments)} comments")

    response = requests.post(
        f"{api_url}/admin/reports",
        headers={"x-api-key": admin_api_key, "Content-Type": "application/json"},
        json={
            "input": title,
            "question": title,
            "intro": "",
            "comments": comments,
            "cluster": cluster_nums,
            "provider": "openai",
            "model": model,
            "workers": workers,
            "prompt": DEFAULT_PROMPTS,
        },
        timeout=60,
    )
    response.raise_for_status()

    slug = response.json().get("slug")
    logger.info(f"Report created: slug={slug}")
    return slug


def wait_for_completion(
    api_url: str,
    admin_api_key: str,
    slug: str,
    timeout_minutes: int = 60,
    poll_interval: int = 30,
) -> None:
    """レポートの分析完了をポーリングで待機"""
    deadline = time.time() + timeout_minutes * 60

    while True:
        if time.time() > deadline:
            raise TimeoutError(f"Report {slug} did not complete within {timeout_minutes} minutes")

        response = requests.get(
            f"{api_url}/admin/reports/{slug}/status/step-json",
            headers={"x-api-key": admin_api_key},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        status = data.get("status")
        current_step = data.get("current_step", "unknown")
        logger.info(f"Report {slug}: status={status}, step={current_step}")

        if status == "completed":
            return
        if status == "error":
            raise RuntimeError(f"Report {slug} failed at step {current_step}")

        time.sleep(poll_interval)


def wait_for_service(url: str, max_retries: int = 12, interval: int = 5) -> None:
    """サイドカーサービスの起動を待機"""
    for i in range(max_retries):
        try:
            response = requests.get(f"{url}/healthcheck", timeout=5)
            if response.status_code == 200:
                logger.info(f"Service {url} is ready")
                return
        except requests.ConnectionError:
            pass
        logger.info(f"Waiting for {url}... ({i + 1}/{max_retries})")
        time.sleep(interval)
    raise RuntimeError(f"Service {url} did not start within {max_retries * interval} seconds")


def download_static_build(
    builder_url: str,
    slug: str,
    output_path: str,
) -> None:
    """static-site-builder から zip をダウンロード"""
    logger.info(f"Requesting static build for slug={slug}")

    response = requests.post(
        f"{builder_url}/build",
        json={"slugs": slug},
        timeout=600,
    )
    response.raise_for_status()

    with open(output_path, "wb") as f:
        f.write(response.content)

    logger.info(f"Static build saved to {output_path}")
```

- [ ] **ステップ 4: テストが通ることを確認**

```bash
python -m pytest tests/test_report_kouchou.py -v
```

- [ ] **ステップ 5: コミット**

```bash
git add src/birdxplorer_etl/scripts/report_kouchou.py tests/test_report_kouchou.py
git commit -m "feat: add report_kouchou module for kouchou-ai API interaction"
```

---

### タスク 3: report_templates — テンプレート生成

**ファイル:**
- 作成: `src/birdxplorer_etl/scripts/report_templates.py`
- 作成: `tests/test_report_templates.py`

- [ ] **ステップ 1: テストを書く**

```python
# tests/test_report_templates.py
import pytest


class TestGenerateReportEntry:
    def test_generates_typescript_entry(self):
        from birdxplorer_etl.scripts.report_templates import generate_report_entry

        entry = generate_report_entry(
            report_id="2",
            year=2026,
            month=2,
            description="テスト説明文",
            slug="test-uuid-123",
        )

        assert '"2"' in entry
        assert "2026年 2月レポート" in entry
        assert "テスト説明文" in entry
        assert "buildReportHref(2026, 2)" in entry
        assert "test-uuid-123" in entry
        assert "/kouchou-ai/2026/02/" in entry


class TestGenerateIndexUpdate:
    def test_generates_iframe_src(self):
        from birdxplorer_etl.scripts.report_templates import generate_index_iframe_src

        src = generate_index_iframe_src(year=2026, month=2, slug="test-uuid-123")

        assert src == "/kouchou-ai/2026/02/test-uuid-123/index.html"


class TestUpdateReportsTs:
    def test_inserts_new_entry_at_top(self):
        from birdxplorer_etl.scripts.report_templates import update_reports_ts

        existing = '''export const REPORT_ITEMS: ReportItem[] = [
  {
    id: "1",
    title: "2026年 1月レポート",'''

        new_entry = '  {\n    id: "2",\n    title: "2026年 2月レポート",'

        result = update_reports_ts(existing, new_entry)

        assert result.index("2月レポート") < result.index("1月レポート")
        assert "REPORT_ITEMS: ReportItem[] = [" in result
```

- [ ] **ステップ 2: テストが失敗することを確認**

```bash
python -m pytest tests/test_report_templates.py -v
```

- [ ] **ステップ 3: 実装**

```python
# src/birdxplorer_etl/scripts/report_templates.py
import re


def generate_report_entry(
    report_id: str,
    year: int,
    month: int,
    description: str,
    slug: str,
) -> str:
    """reports.ts に追加する ReportItem エントリを生成"""
    month_padded = str(month).zfill(2)
    return f"""  {{
    id: "{report_id}",
    title: "{year}年 {month}月レポート",
    description:
      "{description}",
    href: buildReportHref({year}, {month}),
    date: new Date("{year}-{month_padded}-01"),
    kouchouAiPath: `/kouchou-ai/{year}/{month_padded}/{slug}/index.html`,
  }},"""


def generate_index_iframe_src(year: int, month: int, slug: str) -> str:
    """_index.tsx の AutoResizeIframe src パスを生成"""
    month_padded = str(month).zfill(2)
    return f"/kouchou-ai/{year}/{month_padded}/{slug}/index.html"


def update_reports_ts(existing_content: str, new_entry: str) -> str:
    """reports.ts の REPORT_ITEMS 配列の先頭に新エントリを挿入"""
    marker = "export const REPORT_ITEMS: ReportItem[] = ["
    idx = existing_content.index(marker)
    insert_pos = idx + len(marker) + 1  # 改行の後
    return existing_content[:insert_pos] + new_entry + "\n" + existing_content[insert_pos:]


def update_index_tsx(existing_content: str, new_src: str) -> str:
    """_index.tsx の iframe src を更新"""
    pattern = r'src="/kouchou-ai/[^"]*"'
    replacement = f'src="{new_src}"'
    return re.sub(pattern, replacement, existing_content)
```

- [ ] **ステップ 4: テストが通ることを確認**

```bash
python -m pytest tests/test_report_templates.py -v
```

- [ ] **ステップ 5: コミット**

```bash
git add src/birdxplorer_etl/scripts/report_templates.py tests/test_report_templates.py
git commit -m "feat: add report_templates module for Viewer file generation"
```

---

### タスク 4: report_github — GitHub API クライアント

**ファイル:**
- 作成: `src/birdxplorer_etl/scripts/report_github.py`
- 作成: `tests/test_report_github.py`

- [ ] **ステップ 1: テストを書く**

```python
# tests/test_report_github.py
from unittest.mock import MagicMock, patch, call

import pytest


class TestCreatePR:
    @patch("birdxplorer_etl.scripts.report_github.requests")
    def test_creates_branch_and_pr(self, mock_requests):
        from birdxplorer_etl.scripts.report_github import create_report_pr

        # Mock GET for base branch SHA
        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {"object": {"sha": "abc123"}}

        # Mock POST for branch creation
        mock_post_response = MagicMock()
        mock_post_response.status_code = 201
        mock_post_response.json.return_value = {"number": 42, "html_url": "https://github.com/test/pr/42"}

        mock_requests.get.return_value = mock_get_response
        mock_requests.post.return_value = mock_post_response
        mock_requests.put.return_value = mock_post_response

        result = create_report_pr(
            github_token="test-token",
            repo="codeforjapan/BirdXplorer_Viewer",
            base_branch="dev",
            year=2026,
            month=3,
            slug="test-uuid",
            report_description="テスト説明",
            static_files={"index.html": b"<html>test</html>"},
            reports_ts_content="existing content",
            index_tsx_content="existing index content",
        )

        assert result is not None
```

- [ ] **ステップ 2: テストが失敗することを確認**

```bash
python -m pytest tests/test_report_github.py -v
```

- [ ] **ステップ 3: 実装**

```python
# src/birdxplorer_etl/scripts/report_github.py
import base64
import logging

import requests

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _get_file_content(token: str, repo: str, path: str, ref: str) -> tuple[str, str]:
    """GitHub からファイル内容と SHA を取得"""
    resp = requests.get(
        f"{GITHUB_API}/repos/{repo}/contents/{path}",
        headers=_headers(token),
        params={"ref": ref},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def _update_file(token: str, repo: str, path: str, content: str, message: str, branch: str, sha: str | None = None) -> None:
    """GitHub にファイルを作成または更新"""
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(
        f"{GITHUB_API}/repos/{repo}/contents/{path}",
        headers=_headers(token),
        json=body,
        timeout=30,
    )
    resp.raise_for_status()


def _upload_binary_file(token: str, repo: str, path: str, content: bytes, message: str, branch: str) -> None:
    """GitHub にバイナリファイルをアップロード"""
    body = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": branch,
    }
    resp = requests.put(
        f"{GITHUB_API}/repos/{repo}/contents/{path}",
        headers=_headers(token),
        json=body,
        timeout=30,
    )
    resp.raise_for_status()


def create_report_pr(
    github_token: str,
    repo: str,
    base_branch: str,
    year: int,
    month: int,
    slug: str,
    report_description: str,
    static_files: dict[str, bytes],
    reports_ts_content: str,
    index_tsx_content: str,
) -> str | None:
    """Viewer リポに静的ファイルと設定更新の PR を作成"""
    month_padded = str(month).zfill(2)
    branch_name = f"feat/add-report-{year}{month_padded}"

    # 1. base ブランチの最新 SHA を取得
    resp = requests.get(
        f"{GITHUB_API}/repos/{repo}/git/ref/heads/{base_branch}",
        headers=_headers(github_token),
        timeout=30,
    )
    resp.raise_for_status()
    base_sha = resp.json()["object"]["sha"]

    # 2. ブランチ作成
    resp = requests.post(
        f"{GITHUB_API}/repos/{repo}/git/refs",
        headers=_headers(github_token),
        json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        timeout=30,
    )
    resp.raise_for_status()
    logger.info(f"Created branch: {branch_name}")

    # 3. 静的ファイルをアップロード
    for file_path, content in static_files.items():
        dest = f"public/kouchou-ai/{year}/{month_padded}/{file_path}"
        _upload_binary_file(
            github_token, repo, dest, content,
            f"chore: add static file {file_path}", branch_name,
        )
    logger.info(f"Uploaded {len(static_files)} static files")

    # 4. reports.ts を更新
    reports_ts_path = "app/data/reports.ts"
    _, reports_sha = _get_file_content(github_token, repo, reports_ts_path, branch_name)
    _update_file(
        github_token, repo, reports_ts_path, reports_ts_content,
        f"feat: add {year}年 {month}月レポート to reports.ts", branch_name, reports_sha,
    )

    # 5. _index.tsx を更新
    index_tsx_path = "app/routes/_index.tsx"
    _, index_sha = _get_file_content(github_token, repo, index_tsx_path, branch_name)
    _update_file(
        github_token, repo, index_tsx_path, index_tsx_content,
        f"feat: update top page to {year}年 {month}月レポート", branch_name, index_sha,
    )

    # 6. PR 作成
    resp = requests.post(
        f"{GITHUB_API}/repos/{repo}/pulls",
        headers=_headers(github_token),
        json={
            "title": f"{year}年 {month}月 広聴AIレポート追加",
            "body": (
                f"## 概要\n{year}年 {month}月の広聴AIレポートを追加\n\n"
                "## 自動生成\nこのPRは月次レポート自動生成パイプラインにより作成されました。\n\n"
                "## 検証チェックリスト\n"
                "- [ ] レポートページでチャートが正しく表示される\n"
                "- [ ] トップページの広聴AIセクションが更新されている\n"
                "- [ ] クラスタ情報が表示される\n"
            ),
            "head": branch_name,
            "base": base_branch,
        },
        timeout=30,
    )
    resp.raise_for_status()
    pr_url = resp.json()["html_url"]
    logger.info(f"PR created: {pr_url}")
    return pr_url
```

- [ ] **ステップ 4: テストが通ることを確認**

```bash
python -m pytest tests/test_report_github.py -v
```

- [ ] **ステップ 5: コミット**

```bash
git add src/birdxplorer_etl/scripts/report_github.py tests/test_report_github.py
git commit -m "feat: add report_github module for PR creation"
```

---

### タスク 5: report_generator — メインオーケストレーター

**ファイル:**
- 作成: `src/birdxplorer_etl/scripts/report_generator.py`

- [ ] **ステップ 1: 実装**

```python
# src/birdxplorer_etl/scripts/report_generator.py
import argparse
import logging
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timezone

from birdxplorer_etl.scripts.report_db import extract_notes
from birdxplorer_etl.scripts.report_kouchou import (
    create_report,
    download_static_build,
    wait_for_completion,
    wait_for_service,
)
from birdxplorer_etl.scripts.report_github import create_report_pr, _get_file_content
from birdxplorer_etl.scripts.report_templates import (
    generate_index_iframe_src,
    generate_report_entry,
    update_index_tsx,
    update_reports_ts,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _determine_target_month(args) -> tuple[int, int]:
    """対象年月を決定する。指定がなければ前月を自動計算。"""
    if args.target_year and args.target_month:
        return args.target_year, args.target_month

    now = datetime.now(timezone.utc)
    first_of_this_month = now.replace(day=1)
    if first_of_this_month.month == 1:
        return first_of_this_month.year - 1, 12
    return first_of_this_month.year, first_of_this_month.month - 1


def _determine_report_id(reports_ts_content: str) -> str:
    """既存の最大 ID + 1 を返す"""
    import re

    ids = re.findall(r'id:\s*"(\d+)"', reports_ts_content)
    if ids:
        return str(max(int(i) for i in ids) + 1)
    return "1"


def _get_overview(api_url: str, api_key: str, slug: str) -> str:
    """kouchou-ai API からレポートの overview を取得"""
    import requests

    resp = requests.get(
        f"{api_url}/reports/{slug}",
        headers={"x-api-key": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("overview", "")


def main():
    parser = argparse.ArgumentParser(description="月次レポート自動生成")
    parser.add_argument("--db-host", default=os.environ.get("DB_HOST", "localhost"))
    parser.add_argument("--db-port", default=os.environ.get("DB_PORT", "5432"))
    parser.add_argument("--db-user", default=os.environ.get("DB_USER", "postgres"))
    parser.add_argument("--db-pass", default=os.environ.get("DB_PASS", ""))
    parser.add_argument("--db-name", default=os.environ.get("DB_NAME", "postgres"))
    parser.add_argument("--kouchou-api-url", default=os.environ.get("KOUCHOU_API_URL", "http://localhost:8000"))
    parser.add_argument("--static-builder-url", default=os.environ.get("STATIC_BUILDER_URL", "http://localhost:3200"))
    parser.add_argument("--admin-api-key", default=os.environ.get("ADMIN_API_KEY", "admin"))
    parser.add_argument("--public-api-key", default=os.environ.get("PUBLIC_API_KEY", "public"))
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--github-repo", default="codeforjapan/BirdXplorer_Viewer")
    parser.add_argument("--github-base-branch", default="dev")
    parser.add_argument("--target-year", type=int, default=None)
    parser.add_argument("--target-month", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="GitHub PR 作成をスキップ")
    args = parser.parse_args()

    target_year, target_month = _determine_target_month(args)
    month_padded = str(target_month).zfill(2)
    logger.info(f"Target: {target_year}/{target_month}")

    # Step 1: サイドカー起動待ち
    if not args.dry_run or args.kouchou_api_url != "http://localhost:8000":
        logger.info("Waiting for sidecar services...")
        wait_for_service(args.kouchou_api_url)
        wait_for_service(args.static_builder_url)

    # Step 2: DB からノート抽出
    csv_path = tempfile.mktemp(suffix=".csv", prefix=f"report-{target_year}{month_padded}-")
    count = extract_notes(
        target_year=target_year,
        target_month=target_month,
        output_path=csv_path,
        db_host=args.db_host,
        db_port=args.db_port,
        db_user=args.db_user,
        db_pass=args.db_pass,
        db_name=args.db_name,
    )

    if count == 0:
        logger.warning("No notes found for target month. Exiting.")
        return

    logger.info(f"Extracted {count} notes")

    # Step 3: kouchou-ai で分析実行
    title = f"{target_year}年 {target_month}月レポート"
    slug = create_report(
        api_url=args.kouchou_api_url,
        admin_api_key=args.admin_api_key,
        csv_path=csv_path,
        title=title,
    )

    wait_for_completion(
        api_url=args.kouchou_api_url,
        admin_api_key=args.admin_api_key,
        slug=slug,
    )

    # Step 4: overview 取得
    description = _get_overview(args.kouchou_api_url, args.public_api_key, slug)

    # Step 5: 静的ビルド取得
    zip_path = tempfile.mktemp(suffix=".zip", prefix=f"report-{target_year}{month_padded}-")
    download_static_build(
        builder_url=args.static_builder_url,
        slug=slug,
        output_path=zip_path,
    )

    # Step 6: zip 展開
    static_files: dict[str, bytes] = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            if not name.endswith("/"):
                static_files[name] = zf.read(name)
    logger.info(f"Extracted {len(static_files)} files from zip")

    if args.dry_run:
        logger.info("[DRY RUN] Skipping GitHub PR creation")
        logger.info(f"  CSV: {csv_path}")
        logger.info(f"  ZIP: {zip_path}")
        logger.info(f"  Slug: {slug}")
        logger.info(f"  Description: {description[:100]}...")
        logger.info(f"  Static files: {len(static_files)}")
        return

    # Step 7: GitHub PR 作成
    if not args.github_token:
        logger.error("GITHUB_TOKEN is required for PR creation")
        sys.exit(1)

    # Viewer リポの既存ファイルを取得
    reports_ts, _ = _get_file_content(
        args.github_token, args.github_repo, "app/data/reports.ts", args.github_base_branch,
    )
    index_tsx, _ = _get_file_content(
        args.github_token, args.github_repo, "app/routes/_index.tsx", args.github_base_branch,
    )

    # テンプレート生成
    report_id = _determine_report_id(reports_ts)
    new_entry = generate_report_entry(report_id, target_year, target_month, description, slug)
    updated_reports_ts = update_reports_ts(reports_ts, new_entry)
    new_iframe_src = generate_index_iframe_src(target_year, target_month, slug)
    updated_index_tsx = update_index_tsx(index_tsx, new_iframe_src)

    pr_url = create_report_pr(
        github_token=args.github_token,
        repo=args.github_repo,
        base_branch=args.github_base_branch,
        year=target_year,
        month=target_month,
        slug=slug,
        report_description=description,
        static_files=static_files,
        reports_ts_content=updated_reports_ts,
        index_tsx_content=updated_index_tsx,
    )

    logger.info(f"Done! PR: {pr_url}")


if __name__ == "__main__":
    main()
```

- [ ] **ステップ 2: コミット**

```bash
git add src/birdxplorer_etl/scripts/report_generator.py
git commit -m "feat: add report_generator orchestrator script"
```

---

### タスク 6: Dockerfile

**ファイル:**
- 作成: `Dockerfile.report-generator`

- [ ] **ステップ 1: Dockerfile を作成**

```dockerfile
# Dockerfile.report-generator
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY common/ /app/common/
COPY etl/ /app/etl/

RUN pip install --no-cache-dir /app/common /app/etl

CMD ["python", "-m", "birdxplorer_etl.scripts.report_generator"]
```

- [ ] **ステップ 2: ローカルでビルドテスト**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer
docker build -f Dockerfile.report-generator -t report-generator-test .
```

- [ ] **ステップ 3: コミット**

```bash
git add Dockerfile.report-generator
git commit -m "feat: add Dockerfile for report-generator"
```

---

### タスク 7: CDK — ECS タスク定義と EventBridge

**ファイル:**
- 変更: `/Users/ayuki/birdXplorer/BirdXplorer-cdk/lib/config.ts`
- 変更: `/Users/ayuki/birdXplorer/BirdXplorer-cdk/config/dev.json`
- 変更: `/Users/ayuki/birdXplorer/BirdXplorer-cdk/config/prd.json`
- 変更: `/Users/ayuki/birdXplorer/BirdXplorer-cdk/lib/bird_xplorer-stack.ts`

- [ ] **ステップ 1: config.ts に新リポジトリ名を追加**

`EcsConfig` インターフェースに以下を追加:

```typescript
reportGeneratorRepository: string;
kouchouAiApiRepository: string;
kouchouAiStaticBuilderRepository: string;
```

- [ ] **ステップ 2: dev.json / prd.json に ECR リポ名追加**

```json
"reportGeneratorRepository": "birdxplorer-report-generator",
"kouchouAiApiRepository": "birdxplorer-kouchou-ai-api",
"kouchouAiStaticBuilderRepository": "birdxplorer-kouchou-ai-static-builder"
```

- [ ] **ステップ 3: bird_xplorer-stack.ts に ReportGenerator タスク定義追加**

Extract タスクのパターンに従い、以下を追加:

```typescript
// Report Generator Task Definition
const reportGeneratorTaskDef = new ecs.FargateTaskDefinition(this, 'ReportGeneratorTaskDef', {
  cpu: 2048,
  memoryLimitMiB: 4096,
  family: `${props.stage}ReportGeneratorTaskDef`,
  taskRole: backendTaskRole,
  executionRole: backendTaskRole,
});

// Container 1: Orchestrator (essential)
const reportGeneratorRepo = aws_ecr.Repository.fromRepositoryName(
  this, 'reportGeneratorRepo', props.ecs.reportGeneratorRepository,
);
reportGeneratorTaskDef.addContainer('OrchestratorContainer', {
  image: ecs.ContainerImage.fromEcrRepository(reportGeneratorRepo, props.tag),
  essential: true,
  environment: {
    DB_NAME: 'postgres',
    DB_HOST: props.rds.dbInstanceEndpointAddress,
    DB_PORT: props.rds.dbInstanceEndpointPort,
    KOUCHOU_API_URL: 'http://localhost:8000',
    STATIC_BUILDER_URL: 'http://localhost:3200',
    ADMIN_API_KEY: 'admin',
    PUBLIC_API_KEY: 'public',
    GITHUB_REPO: 'codeforjapan/BirdXplorer_Viewer',
    GITHUB_BASE_BRANCH: 'dev',
  },
  secrets: {
    DB_USER: aws_ecs.Secret.fromSecretsManager(props.dbSecret, 'username'),
    DB_PASS: aws_ecs.Secret.fromSecretsManager(props.dbSecret, 'password'),
    GITHUB_TOKEN: aws_ecs.Secret.fromSecretsManager(props.etlSecret, 'GITHUB_TOKEN'),
    OPENAI_API_KEY: aws_ecs.Secret.fromSecretsManager(props.etlSecret, 'OPENAPI_TOKEN'),
  },
  logging: ecs.LogDriver.awsLogs({
    logGroup: new aws_logs.LogGroup(this, 'ReportGeneratorLogGroup', {
      logGroupName: `${props.stage}-${props.serviceName}-reportGeneratorLogGroup`,
      removalPolicy: RemovalPolicy.DESTROY,
      retention: RetentionDays.TWO_MONTHS,
    }),
    streamPrefix: 'reportGenerator',
  }),
});

// Container 2: kouchou-ai API (sidecar)
const kouchouAiApiRepo = aws_ecr.Repository.fromRepositoryName(
  this, 'kouchouAiApiRepo', props.ecs.kouchouAiApiRepository,
);
reportGeneratorTaskDef.addContainer('KouchouAiApiContainer', {
  image: ecs.ContainerImage.fromEcrRepository(kouchouAiApiRepo, props.tag),
  essential: false,
  environment: {
    ADMIN_API_KEY: 'admin',
    PUBLIC_API_KEY: 'public',
    STORAGE_TYPE: 'local',
    ENVIRONMENT: 'production',
  },
  secrets: {
    OPENAI_API_KEY: aws_ecs.Secret.fromSecretsManager(props.etlSecret, 'OPENAPI_TOKEN'),
  },
  portMappings: [{ containerPort: 8000 }],
  logging: ecs.LogDriver.awsLogs({
    logGroup: new aws_logs.LogGroup(this, 'KouchouAiApiLogGroup', {
      logGroupName: `${props.stage}-${props.serviceName}-kouchouAiApiLogGroup`,
      removalPolicy: RemovalPolicy.DESTROY,
      retention: RetentionDays.TWO_MONTHS,
    }),
    streamPrefix: 'kouchouAiApi',
  }),
});

// Container 3: static-site-builder (sidecar)
const kouchouAiStaticRepo = aws_ecr.Repository.fromRepositoryName(
  this, 'kouchouAiStaticRepo', props.ecs.kouchouAiStaticBuilderRepository,
);
reportGeneratorTaskDef.addContainer('StaticSiteBuilderContainer', {
  image: ecs.ContainerImage.fromEcrRepository(kouchouAiStaticRepo, props.tag),
  essential: false,
  environment: {
    NEXT_PUBLIC_API_BASEPATH: 'http://localhost:8000',
    API_BASEPATH: 'http://localhost:8000',
    NEXT_PUBLIC_PUBLIC_API_KEY: 'public',
  },
  portMappings: [{ containerPort: 3200 }],
  logging: ecs.LogDriver.awsLogs({
    logGroup: new aws_logs.LogGroup(this, 'StaticBuilderLogGroup', {
      logGroupName: `${props.stage}-${props.serviceName}-staticBuilderLogGroup`,
      removalPolicy: RemovalPolicy.DESTROY,
      retention: RetentionDays.TWO_MONTHS,
    }),
    streamPrefix: 'staticBuilder',
  }),
});

// EventBridge: 毎月3日 06:00 UTC (15:00 JST)
new events.Rule(this, 'MonthlyReportRule', {
  schedule: events.Schedule.cron({ minute: '0', hour: '6', day: '3' }),
  targets: [
    new targets.EcsTask({
      cluster,
      taskDefinition: reportGeneratorTaskDef,
      assignPublicIp: true,
      taskCount: 1,
      subnetSelection: { subnetType: ec2.SubnetType.PUBLIC },
      securityGroups: [props.sgForBirdXplorerService],
    }),
  ],
});
```

- [ ] **ステップ 4: CDK ビルド確認**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer-cdk
npm run build
```

- [ ] **ステップ 5: コミット**

```bash
git add lib/config.ts config/dev.json config/prd.json lib/bird_xplorer-stack.ts
git commit -m "feat: add ReportGenerator ECS task and monthly EventBridge rule"
```

---

### タスク 8: ローカル統合テスト

**ファイル:** なし（手動テスト手順）

- [ ] **ステップ 1: kouchou-ai を起動**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer_kouchou-ai
git checkout feature/sync-upstream
docker compose up -d api static-site-builder
```

- [ ] **ステップ 2: dry-run テスト（小規模データ）**

```bash
cd /Users/ayuki/birdXplorer/BirdXplorer/etl
python -m birdxplorer_etl.scripts.report_generator \
  --db-host <dev-rds-host> \
  --db-port 5432 \
  --db-user <user> \
  --db-pass <pass> \
  --db-name postgres \
  --kouchou-api-url http://localhost:8000 \
  --static-builder-url http://localhost:3200 \
  --target-year 2026 \
  --target-month 2 \
  --dry-run
```

期待結果:
- CSV が生成される
- kouchou-ai で分析が実行される
- zip がローカルに出力される
- GitHub PR は作成されない

- [ ] **ステップ 3: 通しテスト（GitHub PR 作成まで）**

```bash
python -m birdxplorer_etl.scripts.report_generator \
  --db-host <dev-rds-host> \
  --db-port 5432 \
  --db-user <user> \
  --db-pass <pass> \
  --db-name postgres \
  --kouchou-api-url http://localhost:8000 \
  --static-builder-url http://localhost:3200 \
  --target-year 2026 \
  --target-month 3 \
  --github-token <token> \
  --github-repo codeforjapan/BirdXplorer_Viewer
```

期待結果:
- 3月分のレポートが生成される
- BirdXplorer_Viewer に PR が作成される

- [ ] **ステップ 4: 後片付け**

```bash
docker compose down
```
