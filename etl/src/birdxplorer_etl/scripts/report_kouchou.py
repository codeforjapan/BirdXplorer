import csv
import logging
import time
import uuid
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_PROMPTS = {
    "extraction": (
        "あなたは専門的なリサーチアシスタントです。与えられたテキストから、意見を抽出して整理してください。\n"
        "# 指示\n"
        "* 入出力の例に記載したような形式で文字列のリストを返してください\n"
        "  * 必要な場合は2つの別個の意見に分割してください。多くの場合は1つの議論にまとめる方が望ましいです。\n"
        "* 整理した意見は日本語で出力してください"
    ),
    "initial_labelling": (
        "あなたはKJ法が得意なデータ分析者です。userのinputはグループに集まったラベルです。"
        "なぜそのラベルが一つのグループであるか解説し、表札（label）をつけてください。\n"
        "表札については、グループ内の具体的な論点や特徴を反映した、具体性の高い名称を考案してください。\n"
        "出力はJSONとし、フォーマットは以下のサンプルを参考にしてください。"
    ),
    "merge_labelling": (
        "あなたはデータ分析のエキスパートです。\n"
        "現在、テキストデータの階層クラスタリングを行っています。\n"
        "下層のクラスタ（意見グループ）のタイトルと説明、およびそれらのクラスタが所属する上層のクラスタのテキストのサンプルを与えるので、"
        "上層のクラスタのタイトルと説明を作成してください。"
    ),
    "overview": (
        "あなたはシンクタンクで働く専門のリサーチアシスタントです。\n"
        "チームは特定のテーマに関してパブリック・コンサルテーションを実施し、異なる選択肢の意見グループを分析し始めています。\n"
        "これから意見グループのリストとその簡単な分析が提供されます。\n"
        "あなたの仕事は、調査結果の簡潔な要約を返すことです。要約は非常に簡潔に（最大で1段落、最大4文）まとめ、無意味な言葉を避けてください。\n"
        "出力は日本語で行ってください。"
    ),
}


def wait_for_service(url: str, max_retries: int = 12, interval: int = 5) -> None:
    for i in range(max_retries):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
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
            comments.append({"id": row["comment-id"], "comment": row["comment-body"]})

    slug = str(uuid.uuid4())
    payload = {
        "input": slug,
        "question": title,
        "intro": "",
        "cluster": cluster_nums,
        "model": model,
        "provider": "openai",
        "workers": workers,
        "prompt": DEFAULT_PROMPTS,
        "comments": comments,
        "is_pubcom": True,
    }

    headers = {"x-api-key": admin_api_key}
    resp = requests.post(f"{api_url}/admin/reports", json=payload, headers=headers, timeout=60)
    resp.raise_for_status()

    # kouchou-ai API は null を返す。slug は input フィールドの値（UUID）がそのまま使われる。
    logger.info(f"Report created with slug: {slug}")
    return slug


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
