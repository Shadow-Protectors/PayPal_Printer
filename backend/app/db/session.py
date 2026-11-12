from typing import Generator
from app.config.database import SessionLocal

def get_db() -> Generator:
    db = SessionLocal()
    try:
        from app.services.settings_service import load_platform_settings
        load_platform_settings(db)
        yield db
    finally:
        db.close()
