from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from sqlalchemy.orm import relationship
from app.database import Base


class ParkingSpot(Base):
    __tablename__ = "parking_spots"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)   # e.g. "F1-01", "F2-15"
    location = Column(String(255), nullable=False)           # e.g. "Floor 1"
    floor = Column(Integer, nullable=False, default=1, index=True)
    total_capacity = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    availability = relationship("Availability", back_populates="spot", uselist=False, cascade="all, delete-orphan")
    reservations = relationship("Reservation", back_populates="spot", cascade="all, delete-orphan")
    pricing_rule = relationship("PricingRule", back_populates="spot", uselist=False, cascade="all, delete-orphan")
