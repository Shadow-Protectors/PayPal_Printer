from app.config.settings import settings
from app.db.models.platform_setting import PlatformSetting

EDITABLE = {"PER_PAGE_RATE", "BASE_FEE", "MAX_UPLOAD_MB", "OTP_TTL_MINUTES",
            "MAX_OTP_ATTEMPTS", "MAX_PRINT_RETRIES", "HEARTBEAT_TIMEOUT_SECONDS"}


def load_platform_settings(db):
    for row in db.query(PlatformSetting).all():
        if row.key in EDITABLE:
            setattr(settings, row.key, row.value)


def save_platform_settings(db, data):
    for name, value in data.model_dump(exclude_none=True).items():
        key = name.upper()
        if key in EDITABLE:
            row = db.get(PlatformSetting, key)
            if row is None:
                row = PlatformSetting(key=key)
                db.add(row)
            row.value = value
    db.commit()
