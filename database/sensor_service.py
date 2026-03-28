import argparse
import math
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

import httpx

DB_URL = os.getenv("DB_SERVICE_URL", "http://localhost:8001")
DEFAULT_INTERVAL = float(os.getenv("SENSOR_INTERVAL_SEC", "5"))
DEFAULT_RANDOM_RATE = float(os.getenv("RANDOM_TRAFFIC_RATE", "0.00"))
RANDOM_STAY_MIN_MINUTES = max(30, int(os.getenv("RANDOM_TRAFFIC_MIN_STAY_MINUTES", "30")))
RANDOM_STAY_MAX_MINUTES = max(RANDOM_STAY_MIN_MINUTES, int(os.getenv("RANDOM_TRAFFIC_MAX_STAY_MINUTES", "90")))
RUSH_THRESHOLD = 0.1
DEMAND_SIGMOID_STEEPNESS = 4.0
DEMAND_MIDPOINT = 0.45
MAX_DEMAND_EXTRA = 1.20
RUSH_ON_MIN_MULTIPLIER = 1.08
RUSH_OFF_MAX_MULTIPLIER = 1.04
PROJECTION_LOOKAHEAD_HOURS = 2
RATIO_SMOOTH_ALPHA = 0.4
MIN_BILLABLE_HOURS = 0.5

_smoothed_demand_ratio = 0.0
_random_occupied_until: Dict[int, datetime] = {}


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


def _schedule_random_departure(now: datetime) -> datetime:
    hold_minutes = random.randint(RANDOM_STAY_MIN_MINUTES, RANDOM_STAY_MAX_MINUTES)
    return now + timedelta(minutes=hold_minutes)


def _smooth_demand_multiplier(demand_ratio: float) -> float:
    ratio = max(0.0, min(1.0, demand_ratio))

    min_sig = 1.0 / (1.0 + math.exp(-DEMAND_SIGMOID_STEEPNESS * (0.0 - DEMAND_MIDPOINT)))
    max_sig = 1.0 / (1.0 + math.exp(-DEMAND_SIGMOID_STEEPNESS * (1.0 - DEMAND_MIDPOINT)))
    current_sig = 1.0 / (1.0 + math.exp(-DEMAND_SIGMOID_STEEPNESS * (ratio - DEMAND_MIDPOINT)))

    normalized = (current_sig - min_sig) / (max_sig - min_sig) if max_sig > min_sig else 0.0
    return 1.0 + (MAX_DEMAND_EXTRA * normalized)


def _reservation_based_projection_ratio(
    now: datetime,
    total_spots: int,
    reservations: List[dict],
) -> float:
    if total_spots <= 0:
        return 0.0

    ratios: List[float] = []
    checkpoints = [
        now,
        now + timedelta(minutes=30),
        now + timedelta(hours=1),
    ]

    for checkpoint in checkpoints:
        overlap = {
            item["spot_id"]
            for item in reservations
            if parse_ts(item["start_time"]) <= checkpoint < parse_ts(item["end_time"])
        }

        starts_soon = {
            item["spot_id"]
            for item in reservations
            if checkpoint <= parse_ts(item["start_time"]) < (checkpoint + timedelta(hours=PROJECTION_LOOKAHEAD_HOURS))
        }

        overlap_ratio = len(overlap) / total_spots
        starts_soon_ratio = len(starts_soon) / total_spots
        ratios.append(min(1.0, (0.85 * overlap_ratio) + (0.15 * starts_soon_ratio)))

    return sum(ratios) / len(ratios)


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
            hours = max((end_time - start_time).total_seconds() / 3600.0, MIN_BILLABLE_HOURS)
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
    now = utc_now()
    seen_spots: Set[int] = set()

    changed = 0
    for item in availability:
        spot_id = item["spot_id"]
        seen_spots.add(spot_id)
        current_occupied = bool(item.get("is_occupied", False))
        target_occupied = spot_id in active_spots
        persisted_hold_until = parse_ts(item["occupied_until"]) if item.get("occupied_until") else None
        random_hold_until = _random_occupied_until.get(spot_id) or persisted_hold_until

        if spot_id in reserved_spots:
            _random_occupied_until.pop(spot_id, None)
            random_hold_until = None

        if not target_occupied and random_rate > 0 and spot_id not in reserved_spots:
            if random_hold_until and random_hold_until > now:
                _random_occupied_until[spot_id] = random_hold_until
                target_occupied = True
            else:
                if random_hold_until:
                    _random_occupied_until.pop(spot_id, None)
                    target_occupied = False
                elif current_occupied:
                    _random_occupied_until[spot_id] = _schedule_random_departure(now)
                    target_occupied = True
                elif random.random() < random_rate:
                    _random_occupied_until[spot_id] = _schedule_random_departure(now)
                    target_occupied = True

        target_count = 1 if target_occupied else 0
        current_count = int(item.get("occupied_count", 0))
        target_occupied_until = None
        if target_occupied and spot_id not in active_spots:
            target_occupied_until = _random_occupied_until.get(spot_id)

        current_occupied_until = persisted_hold_until
        target_occupied_until_iso = target_occupied_until.isoformat() if target_occupied_until else None
        current_occupied_until_iso = current_occupied_until.isoformat() if current_occupied_until else None

        if (
            current_occupied == target_occupied
            and current_count == target_count
            and current_occupied_until_iso == target_occupied_until_iso
        ):
            continue

        patch_json(
            client,
            f"/availability/{spot_id}",
            {
                "is_occupied": target_occupied,
                "occupied_count": target_count,
                "occupied_until": target_occupied_until_iso,
            },
        )
        changed += 1

    for spot_id in list(_random_occupied_until):
        if spot_id not in seen_spots:
            _random_occupied_until.pop(spot_id, None)

    return changed

def surge_pricing(client: httpx.Client, active_spots: Set[int]) -> int:  # price surging
    spots: List[dict] = get_json(client, "/spots/", params={"active_only": True})
    pending_reservations: List[dict] = get_json(client, "/reservations/", params={"status": "pending"})
    active_reservations: List[dict] = get_json(client, "/reservations/", params={"status": "active"})
    pricing_rules: List[dict] = get_json(client, "/pricing/")

    if not spots:
        return 0

    global _smoothed_demand_ratio

    active_spot_ids = {spot["id"] for spot in spots}
    pricing_map = {rule["spot_id"]: rule for rule in pricing_rules}

    total_spots = len(active_spot_ids)
    projected_reservations = [
        item for item in (pending_reservations + active_reservations) if item.get("spot_id") in active_spot_ids
    ]

    projected_ratio = _reservation_based_projection_ratio(utc_now(), total_spots, projected_reservations)
    _smoothed_demand_ratio = (RATIO_SMOOTH_ALPHA * projected_ratio) + ((1.0 - RATIO_SMOOTH_ALPHA) * _smoothed_demand_ratio)

    rush_multiplier = round(_smooth_demand_multiplier(_smoothed_demand_ratio), 3)

    currently_rush = any(bool(rule.get("is_rush_now", False)) for rule in pricing_rules)
    if currently_rush:
        should_be_rush = rush_multiplier >= RUSH_OFF_MAX_MULTIPLIER
    else:
        should_be_rush = rush_multiplier >= RUSH_ON_MIN_MULTIPLIER

    changed = 0
    for spot_id in active_spot_ids:
        rule = pricing_map.get(spot_id)
        if not rule:
            continue

        current_rush = bool(rule.get("is_rush_now", False))
        current_multiplier = float(rule.get("rush_multiplier", 1.0))
        if should_be_rush:
            if current_rush == should_be_rush and abs(current_multiplier - rush_multiplier) < 1e-6:
                continue
        elif current_rush == should_be_rush:
            continue

        payload = {"is_rush_now": should_be_rush}
        if should_be_rush:
            payload["rush_multiplier"] = rush_multiplier

        patch_json(client, f"/pricing/{spot_id}", payload)
        changed += 1

    print(
        f"[{utc_now().isoformat()}] pricing_sync projected_ratio={projected_ratio:.2f} "
        f"smoothed_ratio={_smoothed_demand_ratio:.2f} rush={should_be_rush} "
        f"rush_multiplier={rush_multiplier:.3f} changed={changed}"
    )
    return changed

def sync_timed_pricing(client: httpx.Client) -> int: #timed price surge between 1pm and 8pm
    pricing_rules: List[dict] = get_json(client, "/pricing/")
    now = datetime.now()
    current_hour = now.hour

    # Peak hours: 1:00 PM up to but not including 8:00 PM
    should_be_peak = 13 <= current_hour < 20

    changed = 0
    for rule in pricing_rules:
        spot_id = rule["spot_id"]
        current_peak = bool(rule.get("is_peak_now", False))

        if current_peak == should_be_peak:
            continue

        patch_json(client, f"/pricing/{spot_id}", {"is_peak_now": should_be_peak})
        changed += 1

    print(
        f"[{utc_now().isoformat()}] timed_pricing "
        f"hour={current_hour} peak={should_be_peak} changed={changed}"
    )
    return changed

def run_cycle(client: httpx.Client, random_rate: float) -> None:
    active_spots, reservation_changes = sync_reservations(client)
    availability_changes = sync_availability(client, active_spots, random_rate)

    timed_changes = sync_timed_pricing(client)
    rush_changes = surge_pricing(client, active_spots)

    print(
        f"[{utc_now().isoformat()}] reservations={reservation_changes} "
        f"availability={availability_changes} "
        f"timed_peak={timed_changes} rush_surge={rush_changes}"
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
