"""Seed only the configured administrator; no demo infrastructure."""
from app.config.database import SessionLocal, engine
from app.config.settings import settings
from app.config.security import hash_password
from app.db.models.user import User, UserRole


def validate_admin():
    if not settings.ADMIN_EMAIL.strip() or len(settings.ADMIN_PASSWORD) < 12:
        raise RuntimeError("Set ADMIN_EMAIL and ADMIN_PASSWORD (at least 12 characters) before seeding/resetting.")


def seed():
    validate_admin()
    from app.db.migrate import sync_schema
    sync_schema(engine)
    with SessionLocal() as db:
        email = settings.ADMIN_EMAIL.strip().lower()
        admin = db.query(User).filter(User.email == email).first()
        if admin is None:
            admin = User(email=email)
            db.add(admin)
        admin.full_name = settings.ADMIN_NAME
        admin.password_hash = hash_password(settings.ADMIN_PASSWORD)
        admin.role = UserRole.ADMIN
        admin.is_active = True
        db.commit()
    print("Administrator seeded. No departments, agents, printers or customers created.")


if __name__ == "__main__":
    seed()
