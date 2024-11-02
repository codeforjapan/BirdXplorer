import json
from typing import List

from fastapi.testclient import TestClient

from birdxplorer_common.models import Note, Post, Topic, UserEnrollment


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
    assert res_json == {
        "data": [json.loads(d.model_dump_json()) for d in post_samples],
        "meta": {"next": None, "prev": None},
    }


def test_posts_get_limit_and_offset(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?limit=2&offset=1")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(d.model_dump_json()) for d in post_samples[1:3]],
        "meta": {
            "next": "http://testserver/api/v1/data/posts?offset=3&limit=2",
            "prev": "http://testserver/api/v1/data/posts?offset=0&limit=2",
        },
    }


def test_posts_get_has_post_id_filter(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get(f"/api/v1/data/posts/?postIds={post_samples[0].post_id},{post_samples[2].post_id}")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [
            json.loads(post_samples[0].model_dump_json()),
            json.loads(post_samples[2].model_dump_json()),
        ],
        "meta": {"next": None, "prev": None},
    }


def test_posts_get_has_note_id_filter(client: TestClient, post_samples: List[Post], note_samples: List[Note]) -> None:
    response = client.get(f"/api/v1/data/posts/?noteIds={','.join([n.note_id for n in note_samples])}")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [json.loads(post_samples[0].model_dump_json())], "meta": {"next": None, "prev": None}}


def test_posts_get_has_created_at_filter_start_and_end(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtFrom=2006-7-25 00:00:00&createdAtTo=2006-7-30 23:59:59")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [json.loads(post_samples[1].model_dump_json())], "meta": {"next": None, "prev": None}}


def test_posts_get_has_created_at_filter_start(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtFrom=2006-7-25 00:00:00")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(post_samples[i].model_dump_json()) for i in (1, 2, 3, 4)],
        "meta": {"next": None, "prev": None},
    }


def test_posts_get_has_created_at_filter_end(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtTo=2006-7-30 00:00:00")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(post_samples[i].model_dump_json()) for i in (0, 1)],
        "meta": {"next": None, "prev": None},
    }


def test_posts_get_created_at_range_filter_accepts_integer(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtFrom=1153921700000&createdAtTo=1154921800000")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {"data": [json.loads(post_samples[1].model_dump_json())], "meta": {"next": None, "prev": None}}


def test_posts_get_created_at_start_filter_accepts_integer(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtFrom=1153921700000")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(post_samples[i].model_dump_json()) for i in (1, 2, 3, 4)],
        "meta": {"next": None, "prev": None},
    }


def test_posts_get_created_at_end_filter_accepts_integer(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtTo=1154921800000")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(post_samples[i].model_dump_json()) for i in (0, 1)],
        "meta": {"next": None, "prev": None},
    }


def test_posts_get_timestamp_out_of_range(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?createdAtFrom=1153921700&createdAtTo=1153921700")
    assert response.status_code == 422


def test_posts_get_with_media_by_default(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?postIds=2234567890123456791")

    assert response.status_code == 200
    res_json_default = response.json()
    assert res_json_default == {
        "data": [json.loads(post_samples[1].model_dump_json())],
        "meta": {"next": None, "prev": None},
    }


def test_posts_get_with_media_true(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?postIds=2234567890123456791&media=true")

    assert response.status_code == 200
    res_json_default = response.json()
    assert res_json_default == {
        "data": [json.loads(post_samples[1].model_dump_json())],
        "meta": {"next": None, "prev": None},
    }


def test_posts_get_with_media_false(client: TestClient, post_samples: List[Post]) -> None:
    expected_post = post_samples[1].model_copy(update={"media_details": []})
    response = client.get("/api/v1/data/posts/?postIds=2234567890123456791&media=false")

    assert response.status_code == 200
    res_json_default = response.json()
    assert res_json_default == {
        "data": [json.loads(expected_post.model_dump_json())],
        "meta": {"next": None, "prev": None},
    }


def test_posts_search_by_text(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?searchText=https%3A%2F%2Ft.co%2Fxxxxxxxxxxx%2F")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(post_samples[i].model_dump_json()) for i in (0, 2)],
        "meta": {"next": None, "prev": None},
    }


def test_posts_search_by_url(client: TestClient, post_samples: List[Post]) -> None:
    response = client.get("/api/v1/data/posts/?searchUrl=https%3A%2F%2Fexample.com%2Fsh3")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(post_samples[i].model_dump_json()) for i in (2, 3)],
        "meta": {"next": None, "prev": None},
    }


def test_notes_get(client: TestClient, note_samples: List[Note]) -> None:
    response = client.get("/api/v1/data/notes")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(d.model_dump_json()) for d in note_samples],
        "meta": {"next": None, "prev": None},
    }


def test_notes_get_has_note_id_filter(client: TestClient, note_samples: List[Note]) -> None:
    response = client.get(f"/api/v1/data/notes/?noteIds={note_samples[0].note_id}&noteIds={note_samples[2].note_id}")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [
            json.loads(note_samples[0].model_dump_json()),
            json.loads(note_samples[2].model_dump_json()),
        ],
        "meta": {"next": None, "prev": None},
    }


def test_notes_get_has_created_at_filter_from_and_to(client: TestClient, note_samples: List[Note]) -> None:
    response = client.get("/api/v1/data/notes/?createdAtFrom=1152921601000&createdAtTo=1152921603000")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(note_samples[i].model_dump_json()) for i in (1, 2, 3)],
        "meta": {"next": None, "prev": None},
    }


def test_notes_get_has_created_at_filter_from(client: TestClient, note_samples: List[Note]) -> None:
    response = client.get("/api/v1/data/notes/?createdAtFrom=1152921601000")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(note_samples[i].model_dump_json()) for i in (1, 2, 3, 4)],
        "meta": {"next": None, "prev": None},
    }


def test_notes_get_has_created_at_filter_to(client: TestClient, note_samples: List[Note]) -> None:
    response = client.get("/api/v1/data/notes/?createdAtTo=1152921603000")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(note_samples[i].model_dump_json()) for i in (0, 1, 2, 3)],
        "meta": {"next": None, "prev": None},
    }


def test_notes_get_has_topic_id_filter(client: TestClient, note_samples: List[Note]) -> None:
    correct_notes = [note for note in note_samples if note_samples[0].topics[0] in note.topics]
    response = client.get(f"/api/v1/data/notes/?topicIds={note_samples[0].topics[0].topic_id.serialize()}")
    assert response.status_code == 200
    res_json = response.json()
    assert res_json == {
        "data": [json.loads(correct_notes[i].model_dump_json()) for i in range(correct_notes.__len__())],
        "meta": {"next": None, "prev": None},
    }
