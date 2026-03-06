from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.database import engine, Base
from app.routers import parking_spots, availability, reservations, pricing

# Import all models so that Base.metadata picks them up before create_all
import app.models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Smart Parking — Database Service",
    description="Persistent storage service for parking spots, availability, reservations, and pricing.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(parking_spots.router)
app.include_router(availability.router)
app.include_router(reservations.router)
app.include_router(pricing.router)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "database"}
