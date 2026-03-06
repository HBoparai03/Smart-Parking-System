from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AvailabilityBase(BaseModel):
    is_occupied: bool = False
    occupied_count: int = Field(default=0, ge=0)


class AvailabilityCreate(AvailabilityBase):
    spot_id: int


class AvailabilityUpdate(BaseModel):
    is_occupied: Optional[bool] = None
    occupied_count: Optional[int] = Field(None, ge=0)


class AvailabilityResponse(AvailabilityBase):
    id: int
    spot_id: int
    last_sensor_update: datetime

    model_config = {"from_attributes": True}
