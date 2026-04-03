from birdxplorer_etl.scripts.report_templates import (
    generate_index_iframe_src,
    generate_report_entry,
    update_index_tsx,
    update_reports_ts,
)


class TestGenerateReportEntry:
    def test_contains_id(self) -> None:
        result = generate_report_entry("2", 2026, 2, "テスト説明文", "test-uuid")
        assert 'id: "2"' in result

    def test_contains_title(self) -> None:
        result = generate_report_entry("2", 2026, 2, "テスト説明文", "test-uuid")
        assert 'title: "2026年 2月レポート"' in result

    def test_contains_href(self) -> None:
        result = generate_report_entry("2", 2026, 2, "テスト説明文", "test-uuid")
        assert "href: buildReportHref(2026, 2)" in result

    def test_contains_kouchou_ai_path(self) -> None:
        result = generate_report_entry("2", 2026, 2, "テスト説明文", "test-uuid")
        assert "kouchouAiPath: `/kouchou-ai/2026/02/test-uuid/index.html`" in result

    def test_contains_description(self) -> None:
        result = generate_report_entry("2", 2026, 2, "テスト説明文", "test-uuid")
        assert "テスト説明文" in result

    def test_contains_date(self) -> None:
        result = generate_report_entry("2", 2026, 2, "テスト説明文", "test-uuid")
        assert 'date: new Date("2026-02-01")' in result


class TestGenerateIndexIframeSrc:
    def test_returns_correct_path(self) -> None:
        result = generate_index_iframe_src(2026, 2, "test-uuid")
        assert result == "/kouchou-ai/2026/02/test-uuid/index.html"

    def test_zero_pads_month(self) -> None:
        result = generate_index_iframe_src(2026, 1, "slug")
        assert "/01/" in result

    def test_double_digit_month(self) -> None:
        result = generate_index_iframe_src(2026, 12, "slug")
        assert "/12/" in result


class TestUpdateReportsTs:
    def test_inserts_at_array_start(self) -> None:
        existing = "const REPORT_ITEMS: ReportItem[] = [\n" '  {\n    id: "1",\n    title: "old",\n  },\n' "];\n"
        new_entry = '  {\n    id: "2",\n    title: "new",\n  },\n'
        result = update_reports_ts(existing, new_entry)
        # New entry should appear before old entry
        assert result.index('id: "2"') < result.index('id: "1"')

    def test_preserves_existing_entries(self) -> None:
        existing = "const REPORT_ITEMS: ReportItem[] = [\n" '  {\n    id: "1",\n    title: "old",\n  },\n' "];\n"
        new_entry = '  {\n    id: "2",\n    title: "new",\n  },\n'
        result = update_reports_ts(existing, new_entry)
        assert 'id: "1"' in result
        assert 'id: "2"' in result


class TestUpdateIndexTsx:
    def test_replaces_iframe_src(self) -> None:
        existing = '<iframe src="/kouchou-ai/2026/01/old-slug/index.html" />'
        new_src = "/kouchou-ai/2026/02/new-slug/index.html"
        result = update_index_tsx(existing, new_src)
        assert 'src="/kouchou-ai/2026/02/new-slug/index.html"' in result

    def test_removes_old_src(self) -> None:
        existing = '<iframe src="/kouchou-ai/2026/01/old-slug/index.html" />'
        new_src = "/kouchou-ai/2026/02/new-slug/index.html"
        result = update_index_tsx(existing, new_src)
        assert "old-slug" not in result

    def test_preserves_surrounding_content(self) -> None:
        existing = '<div>\n  <iframe src="/kouchou-ai/2026/01/old/index.html" />\n</div>'
        new_src = "/kouchou-ai/2026/02/new/index.html"
        result = update_index_tsx(existing, new_src)
        assert result.startswith("<div>")
        assert result.endswith("</div>")
