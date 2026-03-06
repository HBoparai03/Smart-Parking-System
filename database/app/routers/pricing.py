from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.pricing import PricingRule
from app.models.parking_spot import ParkingSpot
from app.schemas.pricing import PricingRuleCreate, PricingRuleUpdate, PricingRuleResponse

router = APIRouter(prefix="/pricing", tags=["Pricing"])


@router.get("/", response_model=List[PricingRuleResponse])
async def list_pricing_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PricingRule))
    return result.scalars().all()


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
