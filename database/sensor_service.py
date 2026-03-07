import argparse
import os
import random
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import httpx

DB_URL = os.getenv("DB_SERVICE_URL", "http://localhost:8001")
DEFAULT_INTERVAL = float(os.getenv("SENSOR_INTERVAL_SEC", "5"))
DEFAULT_RANDOM_RATE = float(os.getenv("RANDOM_TRAFFIC_RATE", "0.00"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_json(client: httpx.Client, path: str, params: Optional[dict] = None):
    r = client.get(f"{DB_URL}{path}", params=params)
    r.raise_for_status()
    return r.json()


def patch_json(client: httpx.Client, path: str, payload: dict):
    r = client.patch(f"{DB_URL}{path}", json=payload)
    r.raise_for_status()
    return r.json()


def sync_reservations(client: httpx.Client) -> Tuple[Set[int], int]:
    reservations: List[dict] = get_json(client, "/reservations/")
    pricing_rules: List[dict] = get_json(client, "/pricing/")
    pricing_by_spot: Dict[int, float] = {
        rule["spot_id"]: float(rule.get("current_rate", 0.0)) for rule in pricing_rules
    }
    now = utc_now()
    changed = 0

    for item in reservations:
        status = item["status"]
        if status in ("cancelled", "completed"):
            continue

        start_time = parse_ts(item["start_time"])
        end_time = parse_ts(item["end_time"])
        reservation_id = item["id"]
        spot_id = item["spot_id"]

        if now >= end_time:
            hours = max((end_time - start_time).total_seconds() / 3600.0, 0.0)
            rate = pricing_by_spot.get(spot_id, 0.0)
            price_paid = round(rate * hours, 2)
            patch_json(
                client,
                f"/reservations/{reservation_id}",
                {"status": "completed", "price_paid": price_paid},
            )
            changed += 1
            continue

        if status == "pending" and now >= start_time:
            patch_json(client, f"/reservations/{reservation_id}", {"status": "active"})
            changed += 1

    active_reservations: List[dict] = get_json(client, "/reservations/", params={"status": "active"})
    active_spots = {item["spot_id"] for item in active_reservations}
    return active_spots, changed


def sync_availability(client: httpx.Client, active_spots: Set[int], random_rate: float) -> int:
    availability: List[dict] = get_json(client, "/availability/")
    pending_reservations: List[dict] = get_json(client, "/reservations/", params={"status": "pending"})
    reserved_spots = {item["spot_id"] for item in pending_reservations}.union(active_spots)

    changed = 0
    for item in availability:
        spot_id = item["spot_id"]
        current_occupied = bool(item.get("is_occupied", False))
        target_occupied = spot_id in active_spots

        if not target_occupied and random_rate > 0 and spot_id not in reserved_spots:
            if current_occupied and random.random() < random_rate:
                target_occupied = False
            elif not current_occupied and random.random() < random_rate:
                target_occupied = True

        target_count = 1 if target_occupied else 0
        current_count = int(item.get("occupied_count", 0))
        if current_occupied == target_occupied and current_count == target_count:
            continue

        patch_json(
            client,
            f"/availability/{spot_id}",
            {"is_occupied": target_occupied, "occupied_count": target_count},
        )
        changed += 1

    return changed


def run_cycle(client: httpx.Client, random_rate: float) -> None:
    active_spots, reservation_changes = sync_reservations(client)
    availability_changes = sync_availability(client, active_spots, random_rate)
    print(
        f"[{utc_now().isoformat()}] reservations={reservation_changes} "
        f"availability={availability_changes}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Parking sensor simulator")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="Loop interval in seconds")
    parser.add_argument(
        "--random-rate",
        type=float,
        default=DEFAULT_RANDOM_RATE,
        help="Random occupancy chance per cycle for unreserved spots",
    )
    args = parser.parse_args()

    random.seed(42)
    with httpx.Client(timeout=20.0) as client:
        if args.once:
            run_cycle(client, args.random_rate)
            return

        while True:
            try:
                run_cycle(client, args.random_rate)
            except httpx.HTTPError as exc:
                print(f"[{utc_now().isoformat()}] sensor loop error: {exc}")
            time.sleep(max(args.interval, 1.0))


if __name__ == "__main__":
    main()
