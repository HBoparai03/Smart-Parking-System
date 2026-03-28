from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class Availability(Base):
    __tablename__ = "availability"

    id = Column(Integer, primary_key=True, index=True)
    spot_id = Column(Integer, ForeignKey("parking_spots.id", ondelete="CASCADE"), nullable=False, unique=True)
    is_occupied = Column(Boolean, nullable=False, default=False)
    # How many vehicles are currently occupying (for multi-capacity spots)
    occupied_count = Column(Integer, nullable=False, default=0)
    occupied_until = Column(DateTime(timezone=True), nullable=True)
    last_sensor_update = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    spot = relationship("ParkingSpot", back_populates="availability")
