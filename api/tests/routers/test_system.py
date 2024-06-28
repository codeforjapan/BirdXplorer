from fastapi import status
from fastapi.testclient import TestClient


def test_ping(client: TestClient) -> None:
    response = client.get("/api/v1/system/ping")
    assert response.status_code == 200
    assert response.json() == {"message": "pong"}


def test_allowed_cors(client: TestClient) -> None:
    headers = {
        "Access-Control-Request-Method": "GET",
        "Origin": "http://allowed.example.com",
    }

    response = client.options("/api/v1/system/ping", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["access-control-allow-origin"] == headers["Origin"]


def test_disallowed_cors(client: TestClient) -> None:
    headers = {
        "Origin": "http://disallowed.example.com",
        "Access-Control-Request-Method": "GET",
    }

    response = client.options("/api/v1/system/ping", headers=headers)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "access-control-allow-origin" not in response.headers
