import enum
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import relationship
from app.database import Base


class ReservationStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    spot_id = Column(Integer, ForeignKey("parking_spots.id", ondelete="CASCADE"), nullable=False, index=True)
    driver_id = Column(String(100), nullable=False, index=True)  # Simulated driver identifier
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    status = Column(Enum(ReservationStatus), nullable=False, default=ReservationStatus.pending)
    price_paid = Column(Float, nullable=True)  # Locked quote stored at booking time and finalized on completion
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    spot = relationship("ParkingSpot", back_populates="reservations")
