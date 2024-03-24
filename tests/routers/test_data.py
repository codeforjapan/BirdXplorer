import json
from typing import List

from fastapi.testclient import TestClient

from birdxplorer.models import Post, Topic, UserEnrollment


def test_user_enrollments_get(client: TestClient, user_enrollment_samples: List[UserEnrollment]) -> None:
    response = client.get(f"/api/v1/data/user-enrollments/{user_enrollment_samples[0].participant_id}")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json["participantId"] == user_enrollment_samples[0].participant_id


def test_topics_get(client: TestClient, topic_samples: List[Topic]) -> None:
    response = client.get("/api/v1/data/topics")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [d.model_dump(by_alias=True) for d in topic_samples]}


def test_posts_get(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [json.loads(d.model_dump_json()) for d in post_samples]}


def test_posts_get_has_post_id_filter(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get(f"/api/v1/data/posts/?postId={post_samples[0].post_id},{post_samples[2].post_id}")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(post_samples[0].model_dump_json()), json.loads(post_samples[2].model_dump_json())]
    }


def test_posts_get_has_created_at_filter_start_and_end(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtStart=2006-7-25 00:00:00&createdAtEnd=2006-7-30 23:59:59")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [json.loads(post_samples[1].model_dump_json())]}


def test_posts_get_has_created_at_filter_start(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtStart=2006-7-25 00:00:00")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [json.loads(post_samples[i].model_dump_json()) for i in (1, 2)]}


def test_posts_get_has_created_at_filter_end(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtEnd=2006-7-30 00:00:00")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [json.loads(post_samples[i].model_dump_json()) for i in (0, 1)]}


def test_posts_get_created_at_range_filter_accepts_integer(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtStart=1153921700000&createdAtEnd=1154921800000")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [json.loads(post_samples[1].model_dump_json())]}


def test_posts_get_created_at_start_filter_accepts_integer(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtStart=1153921700000")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [json.loads(post_samples[i].model_dump_json()) for i in (1, 2)]}


def test_posts_get_created_at_end_filter_accepts_integer(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtEnd=1154921800000")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [json.loads(post_samples[i].model_dump_json()) for i in (0, 1)]}
