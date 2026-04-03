import re


def generate_report_entry(report_id: str, year: int, month: int, description: str, slug: str) -> str:
    """Generate a TypeScript ReportItem object literal for reports.ts."""
    return (
        "  {\n"
        f'    id: "{report_id}",\n'
        f'    title: "{year}年 {month}月レポート",\n'
        f"    description:\n"
        f'      "{description}",\n'
        f"    href: buildReportHref({year}, {month}),\n"
        f'    date: new Date("{year}-{month:02d}-01"),\n'
        f"    kouchouAiPath: `/kouchou-ai/{year}/{month:02d}/{slug}/index.html`,\n"
        "  },\n"
    )


def generate_index_iframe_src(year: int, month: int, slug: str) -> str:
    """Generate the iframe src path for _index.tsx."""
    return f"/kouchou-ai/{year}/{month:02d}/{slug}/index.html"


def update_reports_ts(existing_content: str, new_entry: str) -> str:
    """Insert a new ReportItem entry at the beginning of the REPORT_ITEMS array."""
    marker = "REPORT_ITEMS: ReportItem[] = ["
    idx = existing_content.index(marker)
    insert_pos = idx + len(marker)
    return existing_content[:insert_pos] + "\n" + new_entry + existing_content[insert_pos:]


def update_index_tsx(existing_content: str, new_src: str) -> str:
    """Replace the iframe src path in _index.tsx."""
    return re.sub(r'src="/kouchou-ai/[^"]*"', f'src="{new_src}"', existing_content)
