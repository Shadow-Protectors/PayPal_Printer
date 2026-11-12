from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from app.config.database import Base

class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    code = Column(String(50), unique=True, index=True, nullable=False) # e.g. "HR", "FIN", "IT"
    name = Column(String(100), unique=True, index=True, nullable=False) # e.g. "Human Resources", "Finance"
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
