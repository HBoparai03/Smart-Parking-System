from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models.parking_spot import ParkingSpot
from app.schemas.parking_spot import ParkingSpotCreate, ParkingSpotUpdate, ParkingSpotResponse

router = APIRouter(prefix="/spots", tags=["Parking Spots"])


@router.get("/", response_model=List[ParkingSpotResponse])
async def list_spots(
    active_only: bool = False,
    floor: Optional[int] = Query(None, ge=1, le=3),
    db: AsyncSession = Depends(get_db),
):
    query = select(ParkingSpot)
    if active_only:
        query = query.where(ParkingSpot.is_active == True)
    if floor is not None:
        query = query.where(ParkingSpot.floor == floor)
    query = query.order_by(ParkingSpot.floor, ParkingSpot.name)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{spot_id}", response_model=ParkingSpotResponse)
async def get_spot(spot_id: int, db: AsyncSession = Depends(get_db)):
    spot = await db.get(ParkingSpot, spot_id)
    if not spot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking spot not found")
    return spot


@router.post("/", response_model=ParkingSpotResponse, status_code=status.HTTP_201_CREATED)
async def create_spot(payload: ParkingSpotCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(ParkingSpot).where(ParkingSpot.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Spot '{payload.name}' already exists")
    try:
        spot = ParkingSpot(**payload.model_dump())
        db.add(spot)
        await db.flush()
        await db.refresh(spot)
        return spot
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Spot '{payload.name}' already exists")


@router.patch("/{spot_id}", response_model=ParkingSpotResponse)
async def update_spot(spot_id: int, payload: ParkingSpotUpdate, db: AsyncSession = Depends(get_db)):
    spot = await db.get(ParkingSpot, spot_id)
    if not spot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking spot not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(spot, field, value)
    await db.flush()
    await db.refresh(spot)
    return spot


@router.delete("/{spot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spot(spot_id: int, db: AsyncSession = Depends(get_db)):
    spot = await db.get(ParkingSpot, spot_id)
    if not spot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking spot not found")
    await db.delete(spot)
