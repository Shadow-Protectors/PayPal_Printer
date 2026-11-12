"""Destructive reset of the configured dedicated SQLite/MySQL database."""
import argparse
from sqlalchemy import inspect, text
from app.config.database import engine
from app.db.base import Base
from app.db.seed import seed, validate_admin


def reset_database():
    validate_admin()
    dialect = engine.dialect.name
    if dialect not in ("sqlite", "mysql", "mariadb"):
        raise RuntimeError("Reset supports SQLite and MySQL/MariaDB only.")
    with engine.connect() as conn:
        switch = "PRAGMA foreign_keys" if dialect == "sqlite" else "SET FOREIGN_KEY_CHECKS"
        conn.execute(text(f"{switch} = 0"))
        conn.commit()
        try:
            quote = engine.dialect.identifier_preparer.quote
            for name in inspect(conn).get_table_names():
                conn.execute(text(f"DROP TABLE {quote(name)}"))
            conn.commit()
        finally:
            conn.execute(text(f"{switch} = 1"))
            conn.commit()
    Base.metadata.create_all(engine)
    seed()
    print("Database reset: one administrator; all other tables empty.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", required=True, help="Permanent deletion; stop services first.")
    parser.parse_args()
    reset_database()
