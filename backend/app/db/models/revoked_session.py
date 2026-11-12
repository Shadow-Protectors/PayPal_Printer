from sqlalchemy import Column, String, DateTime
from datetime import datetime, timezone
from app.config.database import Base


class RevokedSession(Base):
    __tablename__ = 'revoked_sessions'
    token_hash = Column(String(64), primary_key=True)
    revoked_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
