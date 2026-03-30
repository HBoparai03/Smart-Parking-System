import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select
from app.database import get_db
from app.models.availability import Availability
from app.models.reservation import Reservation, ReservationStatus
from app.models.pricing import PricingRule
from app.models.parking_spot import ParkingSpot
from app.schemas.pricing import (
    PricingQuoteRequest,
    PricingQuoteResponse,
    PricingRuleCreate,
    PricingRuleResponse,
    PricingRuleUpdate,
)

router = APIRouter(prefix="/pricing", tags=["Pricing"])

MIN_BOOKING_MINUTES = 30
MAX_BOOKING_HOURS = 12
RUSH_THRESHOLD = 0.10
RUSH_EXP_STEEPNESS = 2.5
DEMAND_SIGMOID_STEEPNESS = 4.0
DEMAND_MIDPOINT = 0.45
MAX_DEMAND_EXTRA = 1.20
PROJECTION_LOOKAHEAD_HOURS = 2
RATIO_SMOOTH_ALPHA = 0.40


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Datetime values must include timezone information",
        )
    return value.astimezone(timezone.utc)


def _current_hour_floor_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def _smooth_demand_multiplier(demand_ratio: float) -> float:
    ratio = max(0.0, min(1.0, demand_ratio))

    min_sig = 1.0 / (1.0 + math.exp(-DEMAND_SIGMOID_STEEPNESS * (0.0 - DEMAND_MIDPOINT)))
    max_sig = 1.0 / (1.0 + math.exp(-DEMAND_SIGMOID_STEEPNESS * (1.0 - DEMAND_MIDPOINT)))
    current_sig = 1.0 / (1.0 + math.exp(-DEMAND_SIGMOID_STEEPNESS * (ratio - DEMAND_MIDPOINT)))

    normalized = (current_sig - min_sig) / (max_sig - min_sig) if max_sig > min_sig else 0.0
    return 1.0 + (MAX_DEMAND_EXTRA * normalized)


def _availability_occupied_spots_at(
    midpoint: datetime,
    availability_items: List[Availability],
    active_spot_ids: set[int],
    reserved_overlap_spots: set[int],
) -> set[int]:
    occupied: set[int] = set()

    for item in availability_items:
        if item.spot_id not in active_spot_ids or item.spot_id in reserved_overlap_spots:
            continue
        if not item.is_occupied:
            continue

        occupied_until = item.occupied_until.astimezone(timezone.utc) if item.occupied_until else None
        if occupied_until and midpoint >= occupied_until:
            continue

        occupied.add(item.spot_id)

    return occupied


def _overlap_ratio(
    midpoint: datetime,
    reservations: List[Reservation],
    availability_items: List[Availability],
    active_spot_ids: set[int],
    total_spots: int,
) -> float:
    reserved_overlap_spots = {
        reservation.spot_id
        for reservation in reservations
        if reservation.start_time <= midpoint < reservation.end_time
    }
    occupied = reserved_overlap_spots.union(
        _availability_occupied_spots_at(midpoint, availability_items, active_spot_ids, reserved_overlap_spots)
    )
    return min(len(occupied) / max(total_spots, 1), 1.0)


def _starts_soon_ratio(midpoint: datetime, reservations: List[Reservation], total_spots: int) -> float:
    lookahead_end = midpoint + timedelta(hours=PROJECTION_LOOKAHEAD_HOURS)
    starting_soon = {
        reservation.spot_id
        for reservation in reservations
        if midpoint <= reservation.start_time < lookahead_end
    }
    return min(len(starting_soon) / max(total_spots, 1), 1.0)


def _is_peak_hour(ts: datetime) -> bool:
    local_hour = ts.astimezone().hour
    return 13 <= local_hour < 20


def _validate_quote_window(start_utc: datetime, end_utc: datetime) -> timedelta:
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
    if start_utc < _current_hour_floor_utc():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_time cannot be before the current hour",
        )
    return duration


async def build_pricing_quote(
    db: AsyncSession,
    spot_id: int,
    start_utc: datetime,
    end_utc: datetime,
    exclude_reservation_id: Optional[int] = None,
) -> PricingQuoteResponse:
    duration = _validate_quote_window(start_utc, end_utc)

    spot = await db.get(ParkingSpot, spot_id)
    if not spot or not spot.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active parking spot not found")

    rule_result = await db.execute(select(PricingRule).where(PricingRule.spot_id == spot_id))
    rule = rule_result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing rule not found")

    spots_result = await db.execute(select(ParkingSpot.id).where(ParkingSpot.is_active == True))
    active_spot_ids = {row[0] for row in spots_result.all()}
    total_active_spots = len(active_spot_ids)
    if total_active_spots == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No active spots available")

    reservation_filters = [
        Reservation.status.in_([ReservationStatus.pending, ReservationStatus.active]),
        Reservation.spot_id.in_(active_spot_ids),
        Reservation.start_time < (end_utc + timedelta(hours=PROJECTION_LOOKAHEAD_HOURS)),
        Reservation.end_time > start_utc,
    ]
    if exclude_reservation_id is not None:
        reservation_filters.append(Reservation.id != exclude_reservation_id)

    reservation_result = await db.execute(select(Reservation).where(and_(*reservation_filters)))
    projected_reservations = reservation_result.scalars().all()
    availability_result = await db.execute(select(Availability).where(Availability.spot_id.in_(active_spot_ids)))
    availability_items = availability_result.scalars().all()

    total_price = 0.0
    rate_samples: List[float] = []
    demand_samples: List[float] = []
    peak_applied = False

    cursor = start_utc
    smoothed_ratio: float | None = None
    while cursor < end_utc:
        next_tick = min(cursor + timedelta(minutes=30), end_utc)
        segment_hours = (next_tick - cursor).total_seconds() / 3600.0
        midpoint = cursor + (next_tick - cursor) / 2

        overlap_ratio = _overlap_ratio(
            midpoint,
            projected_reservations,
            availability_items,
            active_spot_ids,
            total_active_spots,
        )
        starts_soon_ratio = _starts_soon_ratio(midpoint, projected_reservations, total_active_spots)
        projected_ratio = min(1.0, (0.85 * overlap_ratio) + (0.15 * starts_soon_ratio))

        if smoothed_ratio is None:
            smoothed_ratio = projected_ratio
        else:
            smoothed_ratio = (RATIO_SMOOTH_ALPHA * projected_ratio) + ((1.0 - RATIO_SMOOTH_ALPHA) * smoothed_ratio)

        demand_mult = _smooth_demand_multiplier(smoothed_ratio)
        peak_mult = rule.peak_multiplier if _is_peak_hour(midpoint) else 1.0
        if peak_mult > 1.0:
            peak_applied = True

        segment_rate = float(rule.base_rate) * peak_mult * demand_mult
        total_price += segment_rate * segment_hours

        rate_samples.append(segment_rate)
        demand_samples.append(demand_mult)

        cursor = next_tick

    duration_hours = duration.total_seconds() / 3600.0
    estimated_total = round(total_price, 2)
    estimated_hourly = round((total_price / duration_hours) if duration_hours > 0 else 0.0, 2)
    max_demand_multiplier = max(demand_samples) if demand_samples else 1.0
    max_demand_ratio = max(0.0, min(1.0, (max_demand_multiplier - 1.0) / MAX_DEMAND_EXTRA))

    reasons: List[str] = []
    if peak_applied:
        reasons.append("Peak hour pricing applied (1 PM - 8 PM local time)")
    if max_demand_multiplier > 1.0:
        reasons.append("Projected demand pricing based on selected time slot and near-future booking trend")
        reasons.append("Demand multiplier is smoothly scaled to reduce sudden jumps")
    if not reasons:
        reasons.append("Standard demand pricing")

    return PricingQuoteResponse(
        spot_id=spot_id,
        start_time=start_utc,
        end_time=end_utc,
        duration_hours=round(duration_hours, 2),
        estimated_total=estimated_total,
        estimated_hourly_rate=estimated_hourly,
        peak_time_applied=peak_applied,
        max_demand_ratio=round(max_demand_ratio, 3),
        demand_multiplier_peak=round(max_demand_multiplier, 3),
        reasons=reasons,
    )


@router.get("/", response_model=List[PricingRuleResponse])
async def list_pricing_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PricingRule))
    return result.scalars().all()


@router.post("/quote", response_model=PricingQuoteResponse)
async def get_pricing_quote(payload: PricingQuoteRequest, db: AsyncSession = Depends(get_db)):
    start_utc = _to_utc(payload.start_time)
    end_utc = _to_utc(payload.end_time)
    return await build_pricing_quote(db, payload.spot_id, start_utc, end_utc)


@router.get("/{spot_id}", response_model=PricingRuleResponse)
async def get_pricing(spot_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PricingRule).where(PricingRule.spot_id == spot_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing rule not found")
    return rule


@router.post("/", response_model=PricingRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_pricing_rule(payload: PricingRuleCreate, db: AsyncSession = Depends(get_db)):
    spot = await db.get(ParkingSpot, payload.spot_id)
    if not spot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking spot not found")

    existing = await db.execute(
        select(PricingRule).where(PricingRule.spot_id == payload.spot_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pricing rule already exists for this spot")

    rule = PricingRule(**payload.model_dump())
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return rule


@router.patch("/{spot_id}", response_model=PricingRuleResponse)
async def update_pricing(spot_id: int, payload: PricingRuleUpdate, db: AsyncSession = Depends(get_db)):
    """Called by the Pricing Service to toggle peak mode or update rates."""
    result = await db.execute(
        select(PricingRule).where(PricingRule.spot_id == spot_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pricing rule not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await db.flush()
    await db.refresh(rule)
    return rule
