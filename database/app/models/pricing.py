from sqlalchemy import Column, Integer, Float, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id = Column(Integer, primary_key=True, index=True)
    spot_id = Column(Integer, ForeignKey("parking_spots.id", ondelete="CASCADE"), nullable=False, unique=True)
    base_rate = Column(Float, nullable=False, default=2.50)       # $ per hour
    peak_multiplier = Column(Float, nullable=False, default=1.75) # Applied during peak hours
    is_peak_now = Column(Boolean, nullable=False, default=False)  # Toggled by Pricing Service
    effective_from = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    spot = relationship("ParkingSpot", back_populates="pricing_rule")

    @property
    def current_rate(self) -> float:
        if self.is_peak_now:
            return self.base_rate * self.peak_multiplier
        return self.base_rate
