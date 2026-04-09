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


def _create_blob(token: str, repo: str, content_bytes: bytes) -> str:
    """Create a blob in the repo and return its SHA."""
    url = f"{GITHUB_API}/repos/{repo}/git/blobs"
    encoded = base64.b64encode(content_bytes).decode("ascii")
    resp = requests.post(
        url,
        headers=_headers(token),
        json={"content": encoded, "encoding": "base64"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["sha"]


def _create_tree(token: str, repo: str, base_tree_sha: str, tree_items: list[dict]) -> str:
    """Create a tree object and return its SHA."""
    url = f"{GITHUB_API}/repos/{repo}/git/trees"
    resp = requests.post(
        url,
        headers=_headers(token),
        json={"base_tree": base_tree_sha, "tree": tree_items},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["sha"]


def _create_commit(token: str, repo: str, message: str, tree_sha: str, parent_sha: str) -> str:
    """Create a commit object and return its SHA."""
    url = f"{GITHUB_API}/repos/{repo}/git/commits"
    resp = requests.post(
        url,
        headers=_headers(token),
        json={"message": message, "tree": tree_sha, "parents": [parent_sha]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["sha"]


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
    """Create a PR with report files on GitHub using a single commit via Git Trees API."""
    hdrs = _headers(github_token)
    branch_name = f"feat/add-report-{year}{month:02d}"

    # 1. Get base branch SHA
    ref_url = f"{GITHUB_API}/repos/{repo}/git/ref/heads/{base_branch}"
    resp = requests.get(ref_url, headers=hdrs, timeout=30)
    resp.raise_for_status()
    base_sha = resp.json()["object"]["sha"]

    # 2. Get base tree SHA
    commit_url = f"{GITHUB_API}/repos/{repo}/git/commits/{base_sha}"
    resp = requests.get(commit_url, headers=hdrs, timeout=30)
    resp.raise_for_status()
    base_tree_sha = resp.json()["tree"]["sha"]

    # 3. Build tree items (all files in a single tree)
    tree_items: list[dict] = []

    # Static files
    for filename, content_bytes in static_files.items():
        file_path = f"public/kouchou-ai/{year}/{month:02d}/{filename}"
        blob_sha = _create_blob(github_token, repo, content_bytes)
        tree_items.append({"path": file_path, "mode": "100644", "type": "blob", "sha": blob_sha})
        logger.info(f"Uploaded {file_path}")

    # reports.ts
    reports_blob_sha = _create_blob(github_token, repo, reports_ts_content.encode("utf-8"))
    tree_items.append({"path": "app/data/reports.ts", "mode": "100644", "type": "blob", "sha": reports_blob_sha})
    logger.info("Updated reports.ts")

    # _index.tsx
    index_blob_sha = _create_blob(github_token, repo, index_tsx_content.encode("utf-8"))
    tree_items.append({"path": "app/routes/_index.tsx", "mode": "100644", "type": "blob", "sha": index_blob_sha})
    logger.info("Updated _index.tsx")

    # 4. Create tree
    new_tree_sha = _create_tree(github_token, repo, base_tree_sha, tree_items)

    # 5. Create single commit
    commit_message = f"feat: Add {year}-{month:02d} report"
    new_commit_sha = _create_commit(github_token, repo, commit_message, new_tree_sha, base_sha)

    # 6. Create branch pointing to the new commit
    create_ref_url = f"{GITHUB_API}/repos/{repo}/git/refs"
    resp = requests.post(
        create_ref_url,
        headers=hdrs,
        json={"ref": f"refs/heads/{branch_name}", "sha": new_commit_sha},
        timeout=30,
    )
    resp.raise_for_status()
    logger.info(f"Created branch {branch_name}")

    # 7. Create PR
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
