from typing import List

from fastapi.testclient import TestClient

from birdxplorer_common.models import Post


def test_get_posts_filters_by_language(client: TestClient, post_samples: List[Post]) -> None:
    resp = client.get("/api/v1/data/posts?language=ja")
    assert resp.status_code == 200
    body = resp.json()
    assert all(p["language"] == "ja" for p in body["data"])
    assert body["meta"]["total"] == len(body["data"])
    assert len(body["data"]) >= 1


def test_get_posts_without_language_returns_all(client: TestClient, post_samples: List[Post]) -> None:
    resp = client.get("/api/v1/data/posts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == len(post_samples)
