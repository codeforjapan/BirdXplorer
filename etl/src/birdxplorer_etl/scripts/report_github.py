import base64
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def _headers(token: str) -> dict[str, str]:
    """Return Authorization headers for GitHub API."""
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _get_file_content(token: str, repo: str, path: str, ref: str) -> tuple[str, str]:
    """Fetch file content and SHA from GitHub.

    Returns (content_str, sha_str).
    """
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    resp = requests.get(url, headers=_headers(token), params={"ref": ref}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def _update_file(
    token: str,
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: str,
    sha: Optional[str] = None,
) -> None:
    """Create or update a file on GitHub."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    payload: dict[str, str] = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    if sha is not None:
        payload["sha"] = sha
    resp = requests.put(url, headers=_headers(token), json=payload, timeout=30)
    resp.raise_for_status()


def _upload_binary_file(
    token: str,
    repo: str,
    path: str,
    content_bytes: bytes,
    message: str,
    branch: str,
) -> None:
    """Upload a binary file to GitHub."""
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    encoded = base64.b64encode(content_bytes).decode("ascii")
    payload = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    resp = requests.put(url, headers=_headers(token), json=payload, timeout=60)
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
) -> Optional[str]:
    """Create a PR with report files on GitHub.

    Returns the PR html_url, or None on failure.
    """
    hdrs = _headers(github_token)
    branch_name = f"feat/add-report-{year}{month:02d}"

    # 1. Get base branch SHA
    ref_url = f"{GITHUB_API}/repos/{repo}/git/ref/heads/{base_branch}"
    resp = requests.get(ref_url, headers=hdrs, timeout=30)
    resp.raise_for_status()
    base_sha = resp.json()["object"]["sha"]

    # 2. Create new branch
    create_ref_url = f"{GITHUB_API}/repos/{repo}/git/refs"
    resp = requests.post(
        create_ref_url,
        headers=hdrs,
        json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        timeout=30,
    )
    resp.raise_for_status()
    logger.info(f"Created branch {branch_name}")

    # 3. Upload static files
    for filename, content_bytes in static_files.items():
        file_path = f"public/kouchou-ai/{year}/{month:02d}/{filename}"
        _upload_binary_file(github_token, repo, file_path, content_bytes, f"Add static file {filename}", branch_name)
        logger.info(f"Uploaded {file_path}")

    # 4. Update reports.ts
    reports_ts_path = "app/data/reports.ts"
    try:
        _, reports_sha = _get_file_content(github_token, repo, reports_ts_path, base_branch)
    except requests.HTTPError:
        reports_sha = None
    _update_file(
        github_token,
        repo,
        reports_ts_path,
        reports_ts_content,
        f"Update reports.ts for {year}-{month:02d}",
        branch_name,
        reports_sha,
    )
    logger.info("Updated reports.ts")

    # 5. Update _index.tsx
    index_tsx_path = "app/routes/_index.tsx"
    try:
        _, index_sha = _get_file_content(github_token, repo, index_tsx_path, base_branch)
    except requests.HTTPError:
        index_sha = None
    _update_file(
        github_token,
        repo,
        index_tsx_path,
        index_tsx_content,
        f"Update _index.tsx for {year}-{month:02d}",
        branch_name,
        index_sha,
    )
    logger.info("Updated _index.tsx")

    # 6. Create PR
    pr_url = f"{GITHUB_API}/repos/{repo}/pulls"
    pr_body = f"## {year}年{month}月 Community Notes レポート\n\n{report_description}"
    resp = requests.post(
        pr_url,
        headers=hdrs,
        json={
            "title": f"feat: Add {year}-{month:02d} report",
            "body": pr_body,
            "head": branch_name,
            "base": base_branch,
        },
        timeout=30,
    )
    resp.raise_for_status()
    html_url = resp.json()["html_url"]
    logger.info(f"Created PR: {html_url}")
    return html_url
