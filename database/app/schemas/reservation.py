from datetime import datetime, timedelta, timezone
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from app.models.reservation import ReservationStatus

MIN_BOOKING_MINUTES = 30
MAX_BOOKING_HOURS = 12


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Datetime values must include timezone information")
    return value.astimezone(timezone.utc)


def _current_hour_floor_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


class ReservationBase(BaseModel):
    spot_id: int
    driver_id: str = Field(..., max_length=100, examples=["driver_42"])
    start_time: datetime
    end_time: datetime


class ReservationCreate(ReservationBase):
    @model_validator(mode="after")
    def validate_time_window(self):
        start_utc = _to_utc(self.start_time)
        end_utc = _to_utc(self.end_time)

        if end_utc <= start_utc:
            raise ValueError("end_time must be after start_time")

        duration = end_utc - start_utc
        if duration < timedelta(minutes=MIN_BOOKING_MINUTES):
            raise ValueError(f"Reservation duration must be at least {MIN_BOOKING_MINUTES} minutes")
        if duration > timedelta(hours=MAX_BOOKING_HOURS):
            raise ValueError(f"Reservation duration must be at most {MAX_BOOKING_HOURS} hours")

        if start_utc < _current_hour_floor_utc():
            raise ValueError("start_time cannot be before the current hour")

        return self


class ReservationUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[ReservationStatus] = None
    price_paid: Optional[float] = Field(None, ge=0)

    @model_validator(mode="after")
    def end_after_start_if_both_set(self):
        if self.start_time is not None:
            start_utc = _to_utc(self.start_time)
            if start_utc < _current_hour_floor_utc():
                raise ValueError("start_time cannot be before the current hour")

        if self.start_time is not None and self.end_time is not None:
            start_utc = _to_utc(self.start_time)
            end_utc = _to_utc(self.end_time)
            if end_utc <= start_utc:
                raise ValueError("end_time must be after start_time")

            duration = end_utc - start_utc
            if duration < timedelta(minutes=MIN_BOOKING_MINUTES):
                raise ValueError(f"Reservation duration must be at least {MIN_BOOKING_MINUTES} minutes")
            if duration > timedelta(hours=MAX_BOOKING_HOURS):
                raise ValueError(f"Reservation duration must be at most {MAX_BOOKING_HOURS} hours")
        return self


class ReservationResponse(ReservationBase):
    id: int
    status: ReservationStatus
    price_paid: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
