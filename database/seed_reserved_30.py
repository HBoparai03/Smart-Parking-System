"""
Create a scenario where ~30% of active spots are reserved for the current time window.
Usage: python seed_reserved_30.py

Optional:
  python seed_reserved_30.py --ratio 0.30 --duration-minutes 60
"""

import argparse
import os
import random
from datetime import datetime, timedelta, timezone

import httpx

DB_URL = os.getenv("DB_SERVICE_URL", "http://localhost:8001")


def current_hour_floor_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def to_iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed reservation scenario at a target occupancy ratio")
    parser.add_argument("--ratio", type=float, default=0.30, help="Target reserved ratio for active spots")
    parser.add_argument(
        "--duration-minutes",
        type=int,
        default=60,
        help="Duration of created reservations in minutes (minimum 30)",
    )
    args = parser.parse_args()

    if args.ratio <= 0 or args.ratio > 1:
        raise SystemExit("--ratio must be in the range (0, 1]")
    if args.duration_minutes < 30:
        raise SystemExit("--duration-minutes must be at least 30")

    start_time = current_hour_floor_utc()
    end_time = start_time + timedelta(minutes=args.duration_minutes)

    print(f"Seeding reserved scenario at {DB_URL}")
    print(f"Window: {to_iso_z(start_time)} -> {to_iso_z(end_time)}")

    with httpx.Client(timeout=30.0) as client:
        spots_resp = client.get(f"{DB_URL}/spots/", params={"active_only": True})
        spots_resp.raise_for_status()
        active_spots = spots_resp.json()

        if not active_spots:
            print("No active spots found. Nothing to seed.")
            return

        active_spot_ids = [spot["id"] for spot in active_spots]
        total_spots = len(active_spot_ids)
        target_reserved = max(1, int(round(total_spots * args.ratio)))

        pending_resp = client.get(f"{DB_URL}/reservations/", params={"status": "pending"})
        active_resp = client.get(f"{DB_URL}/reservations/", params={"status": "active"})
        pending_resp.raise_for_status()
        active_resp.raise_for_status()

        existing = pending_resp.json() + active_resp.json()

        reserved_now = set()
        for item in existing:
            spot_id = item["spot_id"]
            if spot_id not in active_spot_ids:
                continue

            item_start = datetime.fromisoformat(item["start_time"].replace("Z", "+00:00"))
            item_end = datetime.fromisoformat(item["end_time"].replace("Z", "+00:00"))
            if item_start < end_time and item_end > start_time:
                reserved_now.add(spot_id)

        already_reserved = len(reserved_now)
        if already_reserved >= target_reserved:
            print(
                f"Already at or above target: {already_reserved}/{total_spots} reserved "
                f"({already_reserved / total_spots:.1%})."
            )
            return

        to_create = target_reserved - already_reserved
        candidates = [spot_id for spot_id in active_spot_ids if spot_id not in reserved_now]

        random.seed(42)
        random.shuffle(candidates)
        selected = candidates[:to_create]

        created = 0
        failed = 0
        for idx, spot_id in enumerate(selected, start=1):
            payload = {
                "spot_id": spot_id,
                "driver_id": f"scenario_driver_{idx:03d}",
                "start_time": to_iso_z(start_time),
                "end_time": to_iso_z(end_time),
            }
            resp = client.post(f"{DB_URL}/reservations/", json=payload)
            if resp.status_code in (200, 201):
                created += 1
            else:
                failed += 1
                print(f"[!] Failed spot_id={spot_id}: {resp.status_code} {resp.text}")

        final_reserved = already_reserved + created
        print(
            f"Done. created={created}, failed={failed}, reserved_now={final_reserved}/{total_spots} "
            f"({final_reserved / total_spots:.1%})"
        )


if __name__ == "__main__":
    main()
