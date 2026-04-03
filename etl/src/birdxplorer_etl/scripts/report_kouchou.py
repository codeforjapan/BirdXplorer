import csv
import time
from typing import Optional

import requests

DEFAULT_PROMPTS = {
    "extraction": (
        "あなたは専門的なリサーチアシスタントです。与えられたテキストから、意見を抽出して整理してください。\n"
        "# 指示\n"
        "* 入出力の例に記載したような形式で文字列のリストを返してください\n"
        "  * 必要な場合は2つの別個の意見に分割してください。多くの場合は1つの議論にまとめる方が望ましいです。\n"
        "* 整理した意見は日本語で出力してください"
    ),
}


def wait_for_service(url: str, max_retries: int = 12, interval: int = 5) -> None:
    for i in range(max_retries):
        try:
            resp = requests.get(f"{url}/healthcheck", timeout=10)
            if resp.status_code == 200:
                return
        except requests.ConnectionError:
            pass
        if i < max_retries - 1:
            time.sleep(interval)
    raise RuntimeError(f"Service at {url} did not become healthy after {max_retries} retries")


def create_report(
    api_url: str,
    admin_api_key: str,
    csv_path: str,
    title: str,
    model: str = "gpt-4o-mini",
    cluster_nums: Optional[list[int]] = None,
    workers: int = 30,
) -> str:
    if cluster_nums is None:
        cluster_nums = [20, 100]

    comments: list[dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            comments.append({"comment": row["comment"]})

    payload = {
        "title": title,
        "comments": comments,
        "model": model,
        "cluster_nums": cluster_nums,
        "workers": workers,
        "prompts": DEFAULT_PROMPTS,
    }

    headers = {"x-api-key": admin_api_key}
    resp = requests.post(f"{api_url}/admin/reports", json=payload, headers=headers, timeout=60)
    resp.raise_for_status()

    return resp.json()["slug"]


def wait_for_completion(
    api_url: str,
    admin_api_key: str,
    slug: str,
    timeout_minutes: int = 60,
    poll_interval: int = 30,
) -> None:
    headers = {"x-api-key": admin_api_key}
    deadline = time.time() + timeout_minutes * 60

    while True:
        if time.time() > deadline:
            raise TimeoutError(f"Report {slug} did not complete within {timeout_minutes} minutes")

        resp = requests.get(f"{api_url}/admin/reports/{slug}/status/step-json", headers=headers, timeout=30)
        resp.raise_for_status()
        status = resp.json().get("status")

        if status == "completed":
            return
        if status == "error":
            raise RuntimeError(f"Report {slug} failed with error status")

        time.sleep(poll_interval)


def download_static_build(builder_url: str, slug: str, output_path: str) -> None:
    resp = requests.post(f"{builder_url}/build", json={"slugs": slug}, timeout=300)
    resp.raise_for_status()

    with open(output_path, "wb") as f:
        f.write(resp.content)
