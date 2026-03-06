================================================================================
  SMART PARKING SYSTEM — DATABASE SERVICE
================================================================================

The Database Service is a FastAPI app backed by PostgreSQL. It is the single
source of truth for all persistent data in the system. Every other service
communicates with it over HTTP REST calls — nobody connects to the database
directly.

--------------------------------------------------------------------------------
  HOW TO START THE DATABASE SERVICE
--------------------------------------------------------------------------------

Prerequisites: Docker Desktop must be running.

  cd database
  docker compose up -d          <- starts PostgreSQL on port 5433
  python -m uvicorn app.main:app --reload --port 8001

The API is now live at:  http://<host-ip>:8001
Interactive docs at:     http://<host-ip>:8001/docs

Replace <host-ip> with the host machine's IP on the shared network.
When running everything on one VM, just use: http://localhost:8001

--------------------------------------------------------------------------------
  BASE URL
--------------------------------------------------------------------------------

  http://localhost:8001

All requests and responses use JSON (Content-Type: application/json).

================================================================================
  SENSOR SERVICE
================================================================================

Your job is to simulate IoT sensors updating parking spot occupancy.
You will call ONE endpoint repeatedly as spots change state.

--- Update a spot's occupancy (call this when a sensor fires) ---

  PATCH /availability/{spot_id}
  Body: { "is_occupied": true, "occupied_count": 1 }
  Body: { "is_occupied": false, "occupied_count": 0 }

Example (Python):

  import httpx

  DB_URL = "http://localhost:8001"

  def push_sensor_update(spot_id: int, is_occupied: bool):
      count = 1 if is_occupied else 0
      r = httpx.patch(
          f"{DB_URL}/availability/{spot_id}",
          json={"is_occupied": is_occupied, "occupied_count": count}
      )
      r.raise_for_status()
      return r.json()

--- Read all current availability (optional, for your own checks) ---

  GET /availability/              <- all spots
  GET /availability/{spot_id}    <- one spot

--- CLIENT SIMULATION note ---

  The Client Simulation Service queries:

  GET /spots/?active_only=true          <- list of all active parking spots
  GET /availability/                    <- real-time occupancy for all spots
  GET /reservations/?driver_id=driver_42   <- a driver's existing bookings

  To make a reservation, the client POSTs to the Reservation Service,
  NOT directly to the database. The Reservation Service then writes to the DB.

================================================================================
  DATA AGGREGATION SERVICE (BACKEND API)
================================================================================

Your service collects sensor data and maintains the global state. You will
mostly READ from the database and expose aggregated views to clients.

--- Get all spots with their current availability ---

  GET /spots/
  GET /availability/

--- Get a specific spot ---

  GET /spots/{spot_id}
  GET /availability/{spot_id}

--- Get current pricing for a spot ---

  GET /pricing/{spot_id}
  Response includes "current_rate" which is already calculated
  (base_rate * peak_multiplier if is_peak_now, else base_rate).

--- Full system state snapshot (combine these two calls) ---

  GET /spots/?active_only=true
  GET /availability/

Example (Python) — build a global state dict:

  import httpx

  DB_URL = "http://localhost:8001"

  def get_global_state():
      spots = httpx.get(f"{DB_URL}/spots/").json()
      avail = httpx.get(f"{DB_URL}/availability/").json()
      avail_map = {a["spot_id"]: a for a in avail}
      return [
          {**spot, "availability": avail_map.get(spot["id"])}
          for spot in spots
      ]

--- Health check ---

  GET /health
  Response: { "status": "ok", "service": "database" }

================================================================================
  RESERVATION AND PRICING SERVICE
================================================================================

You handle two things: creating reservations and managing pricing rules.

--- RESERVATIONS ---

Create a reservation (conflict check is automatic — DB rejects double bookings):

  POST /reservations/
  Body:
  {
    "spot_id": 3,
    "driver_id": "driver_42",
    "start_time": "2026-03-10T10:00:00Z",
    "end_time":   "2026-03-10T12:00:00Z"
  }

  Returns 201 on success.
  Returns 409 Conflict if the spot is already booked for that time window.
  Returns 404 if the spot doesn't exist or is inactive.

Update a reservation status (e.g. mark active, completed, or cancelled):

  PATCH /reservations/{reservation_id}
  Body: { "status": "active" }
  Body: { "status": "completed", "price_paid": 5.25 }

  Valid status values: "pending", "active", "completed", "cancelled"

Cancel a reservation:

  DELETE /reservations/{reservation_id}
  (This sets status to "cancelled", does not hard-delete)

List reservations (filter by spot, driver, or status):

  GET /reservations/?spot_id=3
  GET /reservations/?driver_id=driver_42
  GET /reservations/?status=active

Get a single reservation:

  GET /reservations/{reservation_id}

--- PRICING ---

Create a pricing rule for a spot (do this once per spot at setup):

  POST /pricing/
  Body:
  {
    "spot_id": 3,
    "base_rate": 2.50,
    "peak_multiplier": 1.75,
    "is_peak_now": false
  }

Toggle peak mode on/off (call this when demand crosses your threshold):

  PATCH /pricing/{spot_id}
  Body: { "is_peak_now": true }
  Body: { "is_peak_now": false }

Update rates:

  PATCH /pricing/{spot_id}
  Body: { "base_rate": 3.00, "peak_multiplier": 2.0 }

Get current pricing for a spot:

  GET /pricing/{spot_id}
  Response includes "current_rate" — the effective rate right now.

Example (Python) — toggle peak and compute price for a completed reservation:

  import httpx

  DB_URL = "http://localhost:8001"

  def set_peak(spot_id: int, is_peak: bool):
      r = httpx.patch(f"{DB_URL}/pricing/{spot_id}", json={"is_peak_now": is_peak})
      r.raise_for_status()

  def complete_reservation(reservation_id: int, spot_id: int, hours: float):
      pricing = httpx.get(f"{DB_URL}/pricing/{spot_id}").json()
      total = pricing["current_rate"] * hours
      r = httpx.patch(
          f"{DB_URL}/reservations/{reservation_id}",
          json={"status": "completed", "price_paid": round(total, 2)}
      )
      r.raise_for_status()
      return r.json()

================================================================================
  SEED DATA — RUN THIS FIRST TO POPULATE SPOTS
================================================================================

Before testing, run this Python script once to create the parking spots,
availability records, and pricing rules in the database:

  python seed.py   (file is in the database/ folder — run it once to populate)

Or call the endpoints manually:

  POST /spots/      { "name": "A1", "location": "Level 1, Zone A", "total_capacity": 1 }
  POST /availability/  { "spot_id": 1, "is_occupied": false }
  POST /pricing/    { "spot_id": 1, "base_rate": 2.50, "peak_multiplier": 1.75 }

================================================================================
  QUICK REFERENCE — ALL ENDPOINTS
================================================================================

  METHOD   ENDPOINT                        PURPOSE
  -------  ------------------------------  ----------------------------
  GET      /spots/                         List all parking spots (filter by floor)
  GET      /spots/{id}                     Get a single parking spot by ID
  POST     /spots/                         Create a new parking spot
  PATCH    /spots/{id}                     Update a parking spot
  DELETE   /spots/{id}                     Remove a parking spot

  GET      /availability/                  List all spot availability statuses
  GET      /availability/{spot_id}         Get occupancy status for a spot
  POST     /availability/                  Create availability record for a spot
  PATCH    /availability/{spot_id}         Update occupancy (sensor pushes here)

  GET      /reservations/                  List reservations (filter by spot/driver/status)
  GET      /reservations/{id}              Get a single reservation
  POST     /reservations/                  Create a reservation (conflict check automatic)
  PATCH    /reservations/{id}              Update reservation status or price paid
  DELETE   /reservations/{id}              Cancel a reservation

  GET      /pricing/                       List all pricing rules
  GET      /pricing/{spot_id}              Get current rate for a spot
  POST     /pricing/                       Create pricing rule for a spot
  PATCH    /pricing/{spot_id}              Update rates or toggle peak mode

  GET      /health                         Service health check

================================================================================
  FULL INTERACTIVE DOCS
================================================================================

  http://localhost:8001/docs

  Open this in your browser while the service is running. You can test every
  endpoint directly from the browser — no Postman or curl needed.

================================================================================
