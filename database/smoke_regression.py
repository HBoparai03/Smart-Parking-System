import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import psycopg2

from app.database import settings

DB_URL = os.getenv("DB_SERVICE_URL", "http://localhost:8001")
SYNC_DB_URL = settings.SYNC_DATABASE_URL.replace("+psycopg2", "")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def current_hour_floor() -> datetime:
    now = utc_now()
    return now.replace(minute=0, second=0, microsecond=0)


def assert_status(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{response.request.method} {response.request.url} -> {response.status_code}: {response.text}")


def run_sensor_once() -> None:
    result = subprocess.run(
        [sys.executable, "sensor_service.py", "--once"],
        cwd=os.path.dirname(__file__),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)


def wait_for_backend(client: httpx.Client) -> None:
    deadline = time.time() + 20
    last_error = "backend not ready"
    while time.time() < deadline:
        try:
            response = client.get(f"{DB_URL}/health")
            if response.status_code == 200:
                return
            last_error = response.text
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(1)
    raise AssertionError(f"Backend did not become ready: {last_error}")


def force_reservation_window(reservation_id: int, start_time: datetime, end_time: datetime) -> None:
    with psycopg2.connect(SYNC_DB_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE reservations
                SET start_time = %s, end_time = %s
                WHERE id = %s
                """,
                (start_time, end_time, reservation_id),
            )


def main() -> None:
    spot_id = None
    test_name = f"TEST-SMOKE-{uuid.uuid4().hex[:8].upper()}"

    try:
        with httpx.Client(timeout=20.0) as client:
            wait_for_backend(client)

            spot_response = client.post(
                f"{DB_URL}/spots/",
                json={
                    "name": test_name,
                    "location": "Smoke Test",
                    "floor": 1,
                    "total_capacity": 1,
                    "is_active": True,
                },
            )
            assert_status(spot_response, 201)
            spot = spot_response.json()
            spot_id = spot["id"]

            availability_response = client.post(
                f"{DB_URL}/availability/",
                json={"spot_id": spot_id, "is_occupied": False, "occupied_count": 0},
            )
            assert_status(availability_response, 201)

            pricing_response = client.post(
                f"{DB_URL}/pricing/",
                json={
                    "spot_id": spot_id,
                    "base_rate": 2.5,
                    "peak_multiplier": 1.75,
                    "rush_multiplier": 1.5,
                    "is_peak_now": False,
                    "is_rush_now": False,
                },
            )
            assert_status(pricing_response, 201)

            now_floor = current_hour_floor()
            active_start = now_floor
            active_end = active_start + timedelta(hours=1)
            future_start = active_end + timedelta(hours=1)
            future_end = future_start + timedelta(hours=1)

            quote_response = client.post(
                f"{DB_URL}/pricing/quote",
                json={
                    "spot_id": spot_id,
                    "start_time": future_start.isoformat(),
                    "end_time": future_end.isoformat(),
                },
            )
            assert_status(quote_response, 200)
            quote = quote_response.json()
            if quote["estimated_total"] <= 0:
                raise AssertionError("Quote total was not positive")

            reservation_a_response = client.post(
                f"{DB_URL}/reservations/",
                json={
                    "spot_id": spot_id,
                    "driver_id": "smoke_active",
                    "start_time": active_start.isoformat(),
                    "end_time": active_end.isoformat(),
                },
            )
            assert_status(reservation_a_response, 201)
            reservation_a = reservation_a_response.json()

            overlap_response = client.post(
                f"{DB_URL}/reservations/",
                json={
                    "spot_id": spot_id,
                    "driver_id": "smoke_conflict",
                    "start_time": (active_start + timedelta(minutes=30)).isoformat(),
                    "end_time": (active_end + timedelta(minutes=30)).isoformat(),
                },
            )
            assert_status(overlap_response, 409)

            reservation_b_response = client.post(
                f"{DB_URL}/reservations/",
                json={
                    "spot_id": spot_id,
                    "driver_id": "smoke_future",
                    "start_time": future_start.isoformat(),
                    "end_time": future_end.isoformat(),
                },
            )
            assert_status(reservation_b_response, 201)
            reservation_b = reservation_b_response.json()

            conflict_update_response = client.patch(
                f"{DB_URL}/reservations/{reservation_b['id']}",
                json={
                    "start_time": active_start.isoformat(),
                    "end_time": active_end.isoformat(),
                },
            )
            assert_status(conflict_update_response, 409)

            run_sensor_once()

            reservation_a_after_activation = client.get(f"{DB_URL}/reservations/{reservation_a['id']}")
            assert_status(reservation_a_after_activation, 200)
            if reservation_a_after_activation.json()["status"] != "active":
                raise AssertionError("Reservation did not transition to active")

            forced_start = utc_now() - timedelta(hours=1, minutes=1)
            forced_end = utc_now() - timedelta(minutes=1)
            force_reservation_window(reservation_a["id"], forced_start, forced_end)

            run_sensor_once()

            reservation_a_completed = client.get(f"{DB_URL}/reservations/{reservation_a['id']}")
            assert_status(reservation_a_completed, 200)
            reservation_payload = reservation_a_completed.json()
            if reservation_payload["status"] != "completed":
                raise AssertionError("Reservation did not transition to completed")
            if not reservation_payload["price_paid"] or reservation_payload["price_paid"] <= 0:
                raise AssertionError("Completed reservation did not record price_paid")

            print("smoke_regression: ok")
    finally:
        if spot_id is not None:
            with httpx.Client(timeout=20.0) as client:
                delete_response = client.delete(f"{DB_URL}/spots/{spot_id}")
                if delete_response.status_code not in (200, 204, 404):
                    raise AssertionError(f"Cleanup failed: {delete_response.status_code} {delete_response.text}")


if __name__ == "__main__":
    main()
