from typing import List

from fastapi.testclient import TestClient

from birdxplorer.models import Topic, UserEnrollment


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
