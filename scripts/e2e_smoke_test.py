import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import psycopg2


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"
BACKEND_URL = os.getenv("DB_SERVICE_URL", "http://localhost:8001")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8000")
SYNC_DATABASE_URL = os.getenv(
    "SYNC_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql://parkinguser:parkingpass@localhost:5433/smartparking"),
).replace("+psycopg2", "").replace("+asyncpg", "")


def wait_for_json(url: str, expected_status: int = 200, timeout_seconds: int = 60) -> dict:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url)
            if response.status_code == expected_status:
                return response.json()
            last_error = RuntimeError(f"{url} returned {response.status_code}: {response.text}")
        except Exception as exc:  # pragma: no cover - smoke script only
            last_error = exc
        time.sleep(1)

    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def latest_half_hour_slot(now: datetime) -> tuple[datetime, datetime]:
    minute = 30 if now.minute >= 30 else 0
    start = now.replace(minute=minute, second=0, microsecond=0)
    end = start + timedelta(minutes=30)
    return start, end


def run_sensor_once(random_rate: float | None = None) -> None:
    command = [sys.executable, "sensor_service.py", "--once"]
    if random_rate is not None:
        command.extend(["--random-rate", str(random_rate)])
    subprocess.run(command, cwd=str(DATABASE_DIR), check=True)


def force_reservation_end(reservation_id: int, end_time: datetime) -> None:
    with psycopg2.connect(SYNC_DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE reservations SET end_time = %s WHERE id = %s",
                (end_time, reservation_id),
            )
        conn.commit()


def main() -> None:
    print("Waiting for backend health...")
    health = wait_for_json(f"{BACKEND_URL}/health")
    ensure(health.get("status") == "ok", "Backend health check failed")

    print("Checking frontend pages...")
    with httpx.Client(timeout=10.0) as client:
        landing = client.get(f"{FRONTEND_URL}/")
        floor_page = client.get(f"{FRONTEND_URL}/floor/1")
        spots = client.get(f"{FRONTEND_URL}/api/spots", params={"active_only": "true"})
    ensure(landing.status_code == 200, "Landing page did not return HTTP 200")
    ensure("setInterval(loadStats, 5000);" in landing.text, "Landing page is missing dynamic refresh polling")
    ensure(floor_page.status_code == 200, "Floor page did not return HTTP 200")
    ensure(spots.status_code == 200, "Frontend spots proxy failed")
    spots_payload = spots.json()
    ensure(len(spots_payload) >= 60, "Expected at least 60 active spots")

    print("Forcing one auto-occupancy cycle...")
    run_sensor_once(random_rate=1.0)

    with httpx.Client(timeout=10.0) as client:
        availability = client.get(f"{BACKEND_URL}/availability/").json()
        pricing_rules = client.get(f"{BACKEND_URL}/pricing/").json()

    occupied_count = sum(1 for item in availability if item.get("is_occupied"))
    rush_enabled = any(bool(rule.get("is_rush_now")) for rule in pricing_rules)
    print(f"Occupied spots after random fill: {occupied_count}")
    ensure(occupied_count > 0, "Random occupancy did not mark any spots as occupied")
    ensure(rush_enabled, "Rush pricing did not activate from auto-filled occupancy")

    spot_id = spots_payload[0]["id"]
    driver_id = f"smoke_driver_{int(time.time())}"
    now = datetime.now(timezone.utc)
    start_time, end_time = latest_half_hour_slot(now)

    with httpx.Client(timeout=10.0) as client:
        original_pricing = client.get(f"{BACKEND_URL}/pricing/{spot_id}").json()

        clear_response = client.patch(
            f"{BACKEND_URL}/availability/{spot_id}",
            json={"is_occupied": False, "occupied_count": 0, "occupied_until": None},
        )
        ensure(clear_response.status_code == 200, f"Failed to clear test spot occupancy: {clear_response.text}")

        quote_response = client.post(
            f"{BACKEND_URL}/pricing/quote",
            json={
                "spot_id": spot_id,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )
        ensure(quote_response.status_code == 200, f"Quote request failed: {quote_response.text}")
        quote = quote_response.json()

        reservation_response = client.post(
            f"{BACKEND_URL}/reservations/",
            json={
                "spot_id": spot_id,
                "driver_id": driver_id,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )
        ensure(reservation_response.status_code == 201, f"Reservation creation failed: {reservation_response.text}")
        reservation = reservation_response.json()

        locked_total = round(float(reservation["price_paid"]), 2)
        quoted_total = round(float(quote["estimated_total"]), 2)
        print(f"Quoted total: {quoted_total:.2f}")
        print(f"Locked total on reservation: {locked_total:.2f}")
        ensure(locked_total == quoted_total, "Reservation did not store the quoted total")

        mutate_response = client.patch(
            f"{BACKEND_URL}/pricing/{spot_id}",
            json={"base_rate": float(original_pricing["base_rate"]) + 50.0},
        )
        ensure(mutate_response.status_code == 200, f"Failed to mutate pricing rule: {mutate_response.text}")

    print("Completing the reservation after changing live pricing...")
    force_reservation_end(reservation["id"], datetime.now(timezone.utc) - timedelta(minutes=1))
    run_sensor_once(random_rate=1.0)

    with httpx.Client(timeout=10.0) as client:
        completed_response = client.get(f"{BACKEND_URL}/reservations/{reservation['id']}")
        ensure(completed_response.status_code == 200, f"Failed to fetch completed reservation: {completed_response.text}")
        completed = completed_response.json()

        restore_response = client.patch(
            f"{BACKEND_URL}/pricing/{spot_id}",
            json={
                "base_rate": original_pricing["base_rate"],
                "peak_multiplier": original_pricing["peak_multiplier"],
                "rush_multiplier": original_pricing["rush_multiplier"],
                "is_peak_now": original_pricing["is_peak_now"],
                "is_rush_now": original_pricing["is_rush_now"],
            },
        )
        ensure(restore_response.status_code == 200, f"Failed to restore pricing rule: {restore_response.text}")

    final_total = round(float(completed["price_paid"]), 2)
    print(f"Completed reservation total: {final_total:.2f}")
    ensure(completed["status"] == "completed", "Reservation did not complete in the sensor cycle")
    ensure(final_total == quoted_total, "Completed reservation total drifted from the locked quote")

    print("Smoke test passed.")


if __name__ == "__main__":
    main()
