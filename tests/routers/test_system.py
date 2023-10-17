from fastapi.testclient import TestClient


def test_ping(client: TestClient) -> None:
    response = client.get("/api/v1/system/ping")
    assert response.status_code == 200
    assert response.json() == {"message": "pong"}
