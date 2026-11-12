from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, String, Text
from app.config.database import Base


class EmailNotification(Base):
    __tablename__ = 'email_notifications'

    id = Column(String(36), primary_key=True)
    payload = Column(Text, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False, index=True)
    lease_token = Column(String(36), nullable=True)
    created_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
