import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

app = FastAPI(title="COE892 Smart Parking — Frontend")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

DB_SERVICE = os.getenv("DB_SERVICE_URL", "http://localhost:8001")


async def _forward(method: str, path: str, params=None, json=None):
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.request(method, f"{DB_SERVICE}{path}", params=params, json=json)
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Database service is unavailable")

    try:
        payload = r.json()
    except ValueError:
        payload = {"detail": r.text}
    return JSONResponse(status_code=r.status_code, content=payload)


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
    params = {}
    if floor:
        params["floor"] = floor
    return await _forward("GET", "/spots/", params=params)


@app.get("/api/availability")
async def api_availability():
    return await _forward("GET", "/availability/")


@app.get("/api/pricing/{spot_id}")
async def api_pricing(spot_id: int):
    return await _forward("GET", f"/pricing/{spot_id}")


@app.get("/api/reservations")
async def api_reservations(spot_id: int = None, status: str = None):
    params = {}
    if spot_id:
        params["spot_id"] = spot_id
    if status:
        params["status"] = status
    return await _forward("GET", "/reservations/", params=params)


@app.post("/api/reservations")
async def api_create_reservation(request: Request):
    body = await request.json()
    return await _forward("POST", "/reservations/", json=body)
