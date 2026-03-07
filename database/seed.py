"""
Run this once after starting the database service to populate initial data.
Usage: python seed.py

Creates 60 parking spots across 3 floors (20 per floor).
"""

import os
import httpx

DB_URL = os.getenv("DB_SERVICE_URL", "http://localhost:8001")

FLOORS = [
    {"floor": 1, "location": "Floor 1"},
    {"floor": 2, "location": "Floor 2"},
    {"floor": 3, "location": "Floor 3"},
]

SPOTS_PER_FLOOR = 20

PRICING_DEFAULTS = {"base_rate": 2.50, "peak_multiplier": 1.75, "is_peak_now": False}


def seed():
    print(f"Seeding database at {DB_URL}...\n")

    total_created = 0
    total_skipped = 0
    total_failed = 0

    with httpx.Client(timeout=30.0) as client:
        for floor_info in FLOORS:
            floor_num = floor_info["floor"]
            location = floor_info["location"]
            print(f"--- {location} ---")

            for i in range(1, SPOTS_PER_FLOOR + 1):
                spot_name = f"F{floor_num}-{i:02d}"
                spot_data = {
                    "name": spot_name,
                    "location": location,
                    "floor": floor_num,
                    "total_capacity": 1,
                }

                try:
                    r = client.post(f"{DB_URL}/spots/", json=spot_data)
                except httpx.RequestError as exc:
                    print(f"  [!] Failed {spot_name}: {exc}")
                    total_failed += 1
                    continue

                if r.status_code == 201:
                    spot = r.json()
                    spot_id = spot["id"]

                    a = client.post(
                        f"{DB_URL}/availability/",
                        json={"spot_id": spot_id, "is_occupied": False, "occupied_count": 0},
                    )
                    p = client.post(
                        f"{DB_URL}/pricing/",
                        json={"spot_id": spot_id, **PRICING_DEFAULTS},
                    )
                    if a.status_code not in (200, 201) or p.status_code not in (200, 201):
                        print(f"  [!] Partial setup for {spot_name}: availability={a.status_code}, pricing={p.status_code}")
                        total_failed += 1
                        continue
                    print(f"  [+] {spot_name}")
                    total_created += 1

                elif r.status_code == 409:
                    total_skipped += 1
                else:
                    print(f"  [!] Failed {spot_name}: {r.text}")
                    total_failed += 1

    print(f"\nDone. {total_created} created, {total_skipped} already existed, {total_failed} failed.")
    print(f"View at: {DB_URL}/docs")


if __name__ == "__main__":
    seed()
