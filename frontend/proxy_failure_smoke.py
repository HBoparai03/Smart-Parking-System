import os

os.environ["DB_SERVICE_URL"] = "http://127.0.0.1:9"

from fastapi.testclient import TestClient

from app.main import app


def main() -> None:
    client = TestClient(app)

    checks = [
        client.get("/api/spots"),
        client.get("/api/availability"),
        client.post(
            "/api/pricing/quote",
            json={
                "spot_id": 1,
                "start_time": "2099-01-01T13:00:00Z",
                "end_time": "2099-01-01T14:00:00Z",
            },
        ),
    ]

    for response in checks:
        assert response.status_code == 503, response.text
        assert response.json()["detail"] == "Database service is unavailable", response.text

    print("proxy_failure_smoke: ok")


if __name__ == "__main__":
    main()
