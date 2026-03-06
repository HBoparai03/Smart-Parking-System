"""
Run this once after starting the database service to populate initial data.
Usage: python seed.py

Creates 60 parking spots across 3 floors (20 per floor).
"""

import httpx

DB_URL = "http://localhost:8001"
client = httpx.Client(timeout=30.0)

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

            r = client.post(f"{DB_URL}/spots/", json=spot_data)
            if r.status_code == 201:
                spot = r.json()
                spot_id = spot["id"]

                client.post(
                    f"{DB_URL}/availability/",
                    json={"spot_id": spot_id, "is_occupied": False, "occupied_count": 0},
                )
                client.post(
                    f"{DB_URL}/pricing/",
                    json={"spot_id": spot_id, **PRICING_DEFAULTS},
                )
                print(f"  [+] {spot_name}")
                total_created += 1

            elif r.status_code == 409:
                total_skipped += 1
            else:
                print(f"  [!] Failed {spot_name}: {r.text}")

    print(f"\nDone. {total_created} created, {total_skipped} already existed.")
    print(f"View at: {DB_URL}/docs")


if __name__ == "__main__":
    seed()
