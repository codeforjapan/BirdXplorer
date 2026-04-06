import argparse
import logging
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone

import requests

from birdxplorer_etl.scripts.report_db import extract_notes
from birdxplorer_etl.scripts.report_github import _get_file_content, create_report_pr
from birdxplorer_etl.scripts.report_kouchou import (
    create_report,
    download_static_build,
    wait_for_completion,
    wait_for_service,
)
from birdxplorer_etl.scripts.report_templates import (
    generate_index_iframe_src,
    generate_report_entry,
    update_index_tsx,
    update_reports_ts,
)

logger = logging.getLogger(__name__)


def _determine_target_month(args: argparse.Namespace) -> tuple[int, int]:
    """Return (year, month) from args or previous month."""
    if args.target_year is not None and args.target_month is not None:
        return args.target_year, args.target_month
    now = datetime.now(tz=timezone.utc)
    if now.month == 1:
        return now.year - 1, 12
    return now.year, now.month - 1


def _determine_report_id(reports_ts_content: str) -> str:
    """Extract the max existing report ID and return max+1 as string."""
    ids = re.findall(r'id:\s*"(\d+)"', reports_ts_content)
    if not ids:
        return "1"
    max_id = max(int(i) for i in ids)
    return str(max_id + 1)


def _get_overview(api_url: str, api_key: str, slug: str) -> str:
    """Fetch report overview from kouchou-ai API."""
    headers = {"x-api-key": api_key}
    resp = requests.get(f"{api_url}/reports/{slug}", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get("overview", "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate monthly Community Notes report")
    parser.add_argument("--db-host", default=os.environ.get("DB_HOST"))
    parser.add_argument("--db-port", default=os.environ.get("DB_PORT"))
    parser.add_argument("--db-user", default=os.environ.get("DB_USER"))
    parser.add_argument("--db-pass", default=os.environ.get("DB_PASS"))
    parser.add_argument("--db-name", default=os.environ.get("DB_NAME"))
    parser.add_argument("--kouchou-api-url", default="http://localhost:8000")
    parser.add_argument("--static-builder-url", default="http://localhost:3200")
    parser.add_argument("--admin-api-key", default="admin")
    parser.add_argument("--public-api-key", default="public")
    parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--github-repo", default="codeforjapan/BirdXplorer_Viewer")
    parser.add_argument("--github-base-branch", default="dev")
    parser.add_argument("--target-year", type=int, default=None)
    parser.add_argument("--target-month", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    # 1. Determine target month
    year, month = _determine_target_month(args)
    logger.info(f"Target: {year}-{month:02d}")

    # 2. Wait for sidecar services
    wait_for_service(args.kouchou_api_url)
    if not args.dry_run:
        wait_for_service(args.static_builder_url)

    # 3. Extract notes from DB
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, f"notes_{year}_{month:02d}.csv")
        count = extract_notes(
            target_year=year,
            target_month=month,
            output_path=csv_path,
            db_host=args.db_host,
            db_port=args.db_port,
            db_user=args.db_user,
            db_pass=args.db_pass,
            db_name=args.db_name,
        )
        if count == 0:
            logger.info("No notes found. Exiting.")
            return

        # 4. Create report via kouchou-ai
        title = f"BirdXplorer {year}年{month}月 Community Notes レポート"
        slug = create_report(
            api_url=args.kouchou_api_url,
            admin_api_key=args.admin_api_key,
            csv_path=csv_path,
            title=title,
        )
        logger.info(f"Report created with slug: {slug}")

        # 4b. Wait for completion
        wait_for_completion(
            api_url=args.kouchou_api_url,
            admin_api_key=args.admin_api_key,
            slug=slug,
        )

        # 5. Get overview
        overview = _get_overview(args.kouchou_api_url, args.public_api_key, slug)
        logger.info(f"Overview: {overview[:100]}...")

        # 6. Download static build
        zip_path = os.path.join(tmpdir, f"report_{year}_{month:02d}.zip")
        download_static_build(
            builder_url=args.static_builder_url,
            slug=slug,
            output_path=zip_path,
        )
        logger.info(f"Static build downloaded: {zip_path}")

        # 7. Extract zip
        extract_dir = os.path.join(tmpdir, "static")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        logger.info(f"Extracted to: {extract_dir}")

        # 8. Dry-run check
        if args.dry_run:
            logger.info(f"Dry-run mode. CSV: {csv_path}, ZIP: {zip_path}, Slug: {slug}")
            return

        # 9. Get existing files from GitHub
        if not args.github_token:
            logger.error("--github-token or GITHUB_TOKEN is required for PR creation")
            return

        reports_ts_content, _ = _get_file_content(
            args.github_token, args.github_repo, "app/data/reports.ts", args.github_base_branch
        )
        index_tsx_content, _ = _get_file_content(
            args.github_token, args.github_repo, "app/routes/_index.tsx", args.github_base_branch
        )

        # 10. Generate template updates
        report_id = _determine_report_id(reports_ts_content)
        new_entry = generate_report_entry(report_id, year, month, overview, slug)
        updated_reports_ts = update_reports_ts(reports_ts_content, new_entry)
        new_src = generate_index_iframe_src(year, month, slug)
        updated_index_tsx = update_index_tsx(index_tsx_content, new_src)

        # Collect static files as dict[str, bytes]
        static_files: dict[str, bytes] = {}
        for root, _dirs, files in os.walk(extract_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, extract_dir)
                with open(full_path, "rb") as f:
                    static_files[rel_path] = f.read()

        # 11. Create PR
        pr_url = create_report_pr(
            github_token=args.github_token,
            repo=args.github_repo,
            base_branch=args.github_base_branch,
            year=year,
            month=month,
            slug=slug,
            report_description=overview,
            static_files=static_files,
            reports_ts_content=updated_reports_ts,
            index_tsx_content=updated_index_tsx,
        )
        logger.info(f"PR created: {pr_url}")


if __name__ == "__main__":
    main()
