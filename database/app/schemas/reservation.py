from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from app.models.reservation import ReservationStatus


class ReservationBase(BaseModel):
    spot_id: int
    driver_id: str = Field(..., max_length=100, examples=["driver_42"])
    start_time: datetime
    end_time: datetime

    @model_validator(mode="after")
    def end_after_start(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class ReservationCreate(ReservationBase):
    pass


class ReservationUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[ReservationStatus] = None
    price_paid: Optional[float] = Field(None, ge=0)

    @model_validator(mode="after")
    def end_after_start_if_both_set(self):
        if self.start_time is not None and self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class ReservationResponse(ReservationBase):
    id: int
    status: ReservationStatus
    price_paid: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
