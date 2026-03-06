from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PricingRuleBase(BaseModel):
    base_rate: float = Field(default=2.50, gt=0, description="Base rate in $ per hour")
    peak_multiplier: float = Field(default=1.75, gt=1.0, description="Multiplier applied during peak hours")
    is_peak_now: bool = False


class PricingRuleCreate(PricingRuleBase):
    spot_id: int


class PricingRuleUpdate(BaseModel):
    base_rate: Optional[float] = Field(None, gt=0)
    peak_multiplier: Optional[float] = Field(None, gt=1.0)
    is_peak_now: Optional[bool] = None


class PricingRuleResponse(PricingRuleBase):
    id: int
    spot_id: int
    current_rate: float
    effective_from: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
