from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ParkingSpotBase(BaseModel):
    name: str = Field(..., max_length=50, examples=["F1-01"])
    location: str = Field(..., max_length=255, examples=["Floor 1"])
    floor: int = Field(default=1, ge=1, le=3)
    total_capacity: int = Field(default=1, ge=1)
    is_active: bool = True


class ParkingSpotCreate(ParkingSpotBase):
    pass


class ParkingSpotUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=50)
    location: Optional[str] = Field(None, max_length=255)
    floor: Optional[int] = Field(None, ge=1, le=3)
    total_capacity: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None


class ParkingSpotResponse(ParkingSpotBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
