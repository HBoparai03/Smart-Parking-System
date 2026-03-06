import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI(title="COE892 Smart Parking — Frontend")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

DB_SERVICE = os.getenv("DB_SERVICE_URL", "http://localhost:8001")


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/floor/{floor_num}", response_class=HTMLResponse)
async def floor_page(request: Request, floor_num: int):
    if floor_num not in (1, 2, 3):
        floor_num = 1
    return templates.TemplateResponse("floor.html", {
        "request": request,
        "floor_num": floor_num,
    })


# ── API proxy endpoints (called by frontend JS) ──

@app.get("/api/spots")
async def api_spots(floor: int = None):
    async with httpx.AsyncClient(timeout=10.0) as client:
        params = {}
        if floor:
            params["floor"] = floor
        r = await client.get(f"{DB_SERVICE}/spots/", params=params)
        return r.json()


@app.get("/api/availability")
async def api_availability():
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{DB_SERVICE}/availability/")
        return r.json()


@app.get("/api/pricing/{spot_id}")
async def api_pricing(spot_id: int):
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{DB_SERVICE}/pricing/{spot_id}")
        return r.json()


@app.get("/api/reservations")
async def api_reservations(spot_id: int = None, status: str = None):
    async with httpx.AsyncClient(timeout=10.0) as client:
        params = {}
        if spot_id:
            params["spot_id"] = spot_id
        if status:
            params["status"] = status
        r = await client.get(f"{DB_SERVICE}/reservations/", params=params)
        return r.json()


@app.post("/api/reservations")
async def api_create_reservation(request: Request):
    body = await request.json()
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(f"{DB_SERVICE}/reservations/", json=body)
        return r.json()
