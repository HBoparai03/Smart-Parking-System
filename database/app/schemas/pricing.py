from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class PricingRuleBase(BaseModel):
    base_rate: float = Field(default=2.50, gt=0, description="Base rate in $ per hour")
    peak_multiplier: float = Field(default=1.75, gt=1.0, description="Multiplier applied during peak hours")
    rush_multiplier: float = Field(default=1.5, gt=1.0, description="Multiplier applied when garage is nearing full capacity")
    is_peak_now: bool = False
    is_rush_now: bool = False


class PricingRuleCreate(PricingRuleBase):
    spot_id: int


class PricingRuleUpdate(BaseModel):
    base_rate: Optional[float] = Field(None, gt=0)
    peak_multiplier: Optional[float] = Field(None, gt=1.0)
    rush_multiplier: Optional[float] = Field(None, gt=1.0)
    is_peak_now: Optional[bool] = None
    is_rush_now: Optional[bool] = None


class PricingRuleResponse(PricingRuleBase):
    id: int
    spot_id: int
    current_rate: float
    effective_from: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PricingQuoteRequest(BaseModel):
    spot_id: int
    start_time: datetime
    end_time: datetime


class PricingQuoteResponse(BaseModel):
    spot_id: int
    start_time: datetime
    end_time: datetime
    duration_hours: float
    estimated_total: float
    estimated_hourly_rate: float
    peak_time_applied: bool
    max_demand_ratio: float
    demand_multiplier_peak: float
    reasons: List[str]
