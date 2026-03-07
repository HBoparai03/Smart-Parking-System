# Smart Parking System (COE892)

Distributed smart parking simulation with FastAPI services and PostgreSQL.

## Current Scope (Interim)

- Database/API service:
  - Spots, availability, reservations, pricing APIs
  - Alembic migrations + seed script
- Sensor simulation service:
  - Simulates real-time occupancy updates
  - Moves reservations from pending -> active -> completed by time
  - Optional random non-reservation traffic via `--random-rate`
- Frontend service:
  - Landing page and floor map
  - Landing stats show total, available, reserved (now), upcoming, and occupied
  - Reserve spot flow
  - Allows choosing future time windows even if a spot is currently occupied/reserved
  - Floor map marks upcoming reservations without blocking booking
  - API proxy to backend

## Planned Next Scope (Before Final Demo)

- Automatic dynamic pricing updates from demand/peak logic
- Separate aggregation/service orchestration process
- Stronger integration tests and fault scenario demos

## Run Locally

1. Start PostgreSQL

```cmd
cd database
docker compose up -d
```

2. Run migrations

```cmd
cd database
alembic upgrade head
```

3. Start database API (`http://localhost:8001`)

```cmd
cd database
python -m uvicorn app.main:app --reload --port 8001
```

4. Seed sample data

```cmd
cd database
python seed.py
```

5. Start frontend (`http://localhost:8000`)

```cmd
cd frontend
python -m uvicorn app.main:app --reload --port 8000
```

6. Start sensor simulation service

```cmd
cd database
python sensor_service.py
```

Optional random traffic simulation:

```cmd
cd database
python sensor_service.py --random-rate 0.03
```

