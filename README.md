# Smart Parking System (COE892)

Distributed smart parking simulation with FastAPI services and PostgreSQL.

## Final Scope

- Database/API service:
  - Spots, availability, reservations, pricing APIs
  - Alembic migrations + seed script
  - Reservation conflict checks and safer validation
- Sensor simulation service:
  - Simulates real-time occupancy updates
  - Moves reservations from pending -> active -> completed by time
  - Toggles peak and rush pricing state from time-of-day and demand
  - Optional random non-reservation traffic via `--random-rate` with 30-90 minute stays by default
- Frontend service:
  - Landing page and floor map
  - Landing stats show total, available, reserved (now), upcoming, and occupied
  - Reserve spot flow
  - Allows choosing future time windows even if a spot is currently occupied/reserved
  - Floor map marks upcoming reservations without blocking booking
  - API proxy to backend with backend status forwarding

## Service Ownership

- Backend/API: source of truth for spots, availability, reservations, and pricing rules
- Sensor service: periodic orchestration for occupancy, reservation transitions, and pricing mode changes
- Frontend: UI rendering and proxying only; it does not own parking state

## Run Locally

Quick launch:

```cmd
launch_local.cmd
```

Optional random traffic:

```cmd
launch_local.cmd --random-rate 0.03
```

Optional no-seed launch:

```cmd
launch_local.cmd --skip-seed
```

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

Default random traffic stays last 30 to 90 minutes. You can override that with
`RANDOM_TRAFFIC_MIN_STAY_MINUTES` and `RANDOM_TRAFFIC_MAX_STAY_MINUTES`.

Optional 30% reserved scenario seed:

```cmd
cd database
python seed_reserved_30.py
```

## Verify

Static check:

```cmd
python -m compileall database frontend
```

Frontend proxy failure smoke:

```cmd
python frontend\proxy_failure_smoke.py
```

Live backend + sensor smoke:

```cmd
python database\smoke_regression.py
```

Manual UI sanity:

1. Open `http://localhost:8000/floor/1`
2. Open a spot and confirm the modal shows a pricing mode label
3. Create one valid future reservation
4. Try an overlapping reservation and confirm the conflict message appears

