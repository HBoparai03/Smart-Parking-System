from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.database import get_db
from app.models.availability import Availability
from app.models.reservation import Reservation, ReservationStatus
from app.models.parking_spot import ParkingSpot
from app.routers.pricing import build_pricing_quote
from app.schemas.reservation import (
    MAX_BOOKING_HOURS,
    MIN_BOOKING_MINUTES,
    ReservationCreate,
    ReservationResponse,
    ReservationUpdate,
)

router = APIRouter(prefix="/reservations", tags=["Reservations"])


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Datetime values must include timezone information",
        )
    return value.astimezone(timezone.utc)


def _validate_time_window(start_time: datetime, end_time: datetime) -> None:
    start_utc = _to_utc(start_time)
    end_utc = _to_utc(end_time)

    if end_utc <= start_utc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="end_time must be after start_time")

    duration = end_utc - start_utc
    if duration < timedelta(minutes=MIN_BOOKING_MINUTES):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Reservation duration must be at least {MIN_BOOKING_MINUTES} minutes",
        )
    if duration > timedelta(hours=MAX_BOOKING_HOURS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Reservation duration must be at most {MAX_BOOKING_HOURS} hours",
        )

    current_hour_floor = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if start_utc < current_hour_floor:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_time cannot be before the current hour",
        )


async def _validate_physical_occupancy(
    db: AsyncSession,
    spot_id: int,
    start_time: datetime,
) -> None:
    result = await db.execute(select(Availability).where(Availability.spot_id == spot_id))
    availability = result.scalar_one_or_none()
    if not availability or not availability.is_occupied:
        return

    now = datetime.now(timezone.utc)
    active_reservation = await db.execute(
        select(Reservation).where(
            and_(
                Reservation.spot_id == spot_id,
                Reservation.status == ReservationStatus.active,
                Reservation.start_time <= now,
                Reservation.end_time > now,
            )
        )
    )
    if active_reservation.scalar_one_or_none():
        return

    occupied_until = availability.occupied_until.astimezone(timezone.utc) if availability.occupied_until else None
    blocked_until = occupied_until or (now + timedelta(minutes=MIN_BOOKING_MINUTES))

    if _to_utc(start_time) < blocked_until:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Spot is currently occupied and unavailable for the requested start time",
        )


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
    _validate_time_window(payload.start_time, payload.end_time)

    spot = await db.get(ParkingSpot, payload.spot_id)
    if not spot or not spot.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active parking spot not found")

    await _validate_physical_occupancy(db, payload.spot_id, payload.start_time)

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

    quote = await build_pricing_quote(db, payload.spot_id, _to_utc(payload.start_time), _to_utc(payload.end_time))
    reservation = Reservation(**payload.model_dump(), price_paid=quote.estimated_total)
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
    if "start_time" in updates or "end_time" in updates:
        _validate_time_window(new_start, new_end)

    if ("start_time" in updates or "end_time" in updates) and reservation.status in (
        ReservationStatus.pending,
        ReservationStatus.active,
    ):
        await _validate_physical_occupancy(db, reservation.spot_id, new_start)

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

        quote = await build_pricing_quote(
            db,
            reservation.spot_id,
            _to_utc(new_start),
            _to_utc(new_end),
            exclude_reservation_id=reservation.id,
        )
        updates["price_paid"] = quote.estimated_total

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
