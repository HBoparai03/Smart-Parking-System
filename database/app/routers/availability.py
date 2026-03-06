from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.availability import Availability
from app.models.parking_spot import ParkingSpot
from app.schemas.availability import AvailabilityCreate, AvailabilityUpdate, AvailabilityResponse

router = APIRouter(prefix="/availability", tags=["Availability"])


@router.get("/", response_model=List[AvailabilityResponse])
async def list_availability(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Availability))
    return result.scalars().all()


@router.get("/{spot_id}", response_model=AvailabilityResponse)
async def get_availability(spot_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Availability).where(Availability.spot_id == spot_id)
    )
    avail = result.scalar_one_or_none()
    if not avail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability record not found")
    return avail


@router.post("/", response_model=AvailabilityResponse, status_code=status.HTTP_201_CREATED)
async def create_availability(payload: AvailabilityCreate, db: AsyncSession = Depends(get_db)):
    spot = await db.get(ParkingSpot, payload.spot_id)
    if not spot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking spot not found")

    existing = await db.execute(
        select(Availability).where(Availability.spot_id == payload.spot_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Availability record already exists for this spot")

    avail = Availability(**payload.model_dump())
    db.add(avail)
    await db.flush()
    await db.refresh(avail)
    return avail


@router.patch("/{spot_id}", response_model=AvailabilityResponse)
async def update_availability(spot_id: int, payload: AvailabilityUpdate, db: AsyncSession = Depends(get_db)):
    """Called by the Sensor Service to push real-time occupancy updates."""
    result = await db.execute(
        select(Availability).where(Availability.spot_id == spot_id)
    )
    avail = result.scalar_one_or_none()
    if not avail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability record not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(avail, field, value)
    await db.flush()
    await db.refresh(avail)
    return avail
