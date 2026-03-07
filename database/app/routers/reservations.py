from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.database import get_db
from app.models.reservation import Reservation, ReservationStatus
from app.models.parking_spot import ParkingSpot
from app.schemas.reservation import ReservationCreate, ReservationUpdate, ReservationResponse

router = APIRouter(prefix="/reservations", tags=["Reservations"])


@router.get("/", response_model=List[ReservationResponse])
async def list_reservations(
    spot_id: Optional[int] = Query(None),
    driver_id: Optional[str] = Query(None),
    reservation_status: Optional[ReservationStatus] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
):
    query = select(Reservation)
    if spot_id is not None:
        query = query.where(Reservation.spot_id == spot_id)
    if driver_id:
        query = query.where(Reservation.driver_id == driver_id)
    if reservation_status:
        query = query.where(Reservation.status == reservation_status)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{reservation_id}", response_model=ReservationResponse)
async def get_reservation(reservation_id: int, db: AsyncSession = Depends(get_db)):
    reservation = await db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    return reservation


@router.post("/", response_model=ReservationResponse, status_code=status.HTTP_201_CREATED)
async def create_reservation(payload: ReservationCreate, db: AsyncSession = Depends(get_db)):
    spot = await db.get(ParkingSpot, payload.spot_id)
    if not spot or not spot.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active parking spot not found")

    # Conflict check: reject overlapping active/pending reservations for same spot
    conflict = await db.execute(
        select(Reservation).where(
            and_(
                Reservation.spot_id == payload.spot_id,
                Reservation.status.in_([ReservationStatus.pending, ReservationStatus.active]),
                Reservation.start_time < payload.end_time,
                Reservation.end_time > payload.start_time,
            )
        )
    )
    if conflict.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Spot is already reserved for the requested time window",
        )

    reservation = Reservation(**payload.model_dump())
    db.add(reservation)
    await db.flush()
    await db.refresh(reservation)
    return reservation


@router.patch("/{reservation_id}", response_model=ReservationResponse)
async def update_reservation(
    reservation_id: int, payload: ReservationUpdate, db: AsyncSession = Depends(get_db)
):
    reservation = await db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    updates = payload.model_dump(exclude_unset=True)
    new_start = updates.get("start_time", reservation.start_time)
    new_end = updates.get("end_time", reservation.end_time)
    if new_end <= new_start:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="end_time must be after start_time")

    if ("start_time" in updates or "end_time" in updates) and reservation.status in (
        ReservationStatus.pending,
        ReservationStatus.active,
    ):
        conflict = await db.execute(
            select(Reservation).where(
                and_(
                    Reservation.id != reservation.id,
                    Reservation.spot_id == reservation.spot_id,
                    Reservation.status.in_([ReservationStatus.pending, ReservationStatus.active]),
                    Reservation.start_time < new_end,
                    Reservation.end_time > new_start,
                )
            )
        )
        if conflict.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Spot is already reserved for the requested time window",
            )

    for field, value in updates.items():
        setattr(reservation, field, value)
    await db.flush()
    await db.refresh(reservation)
    return reservation


@router.delete("/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reservation(reservation_id: int, db: AsyncSession = Depends(get_db)):
    reservation = await db.get(Reservation, reservation_id)
    if not reservation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    reservation.status = ReservationStatus.cancelled
    await db.flush()
