from sqlalchemy import Column, String, JSON
from app.config.database import Base


class PlatformSetting(Base):
    __tablename__ = "platform_settings"
    key = Column(String(64), primary_key=True)
    value = Column(JSON, nullable=False)
