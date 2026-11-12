import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import inspect, text
from app.config.database import engine
from app.db.base import Base


def sync_schema(target_engine):
    """Add missing model columns; fail visibly if a schema upgrade cannot complete."""
    Base.metadata.create_all(bind=target_engine)
    inspector = inspect(target_engine)
    quote = target_engine.dialect.identifier_preparer.quote
    with target_engine.begin() as connection:
        if target_engine.dialect.name in ("mysql", "mariadb") and inspector.has_table("users"):
            columns = {col["name"]: col for col in inspector.get_columns("users")}
            if "password_hash" in columns and not columns["password_hash"].get("nullable", True):
                connection.execute(text("ALTER TABLE users MODIFY COLUMN password_hash VARCHAR(255) NULL"))
        for table_name, table in Base.metadata.tables.items():
            existing = {col["name"] for col in inspector.get_columns(table_name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                column_type = column.type.compile(dialect=target_engine.dialect)
                # Existing rows need an explicit data migration before tightening
                # newly added required columns. Optional ownership/journal columns
                # can safely be added to existing SQLite and MySQL installations.
                statement = f"ALTER TABLE {quote(table_name)} ADD COLUMN {quote(column.name)} {column_type} NULL"
                connection.execute(text(statement))
        if inspector.has_table("printers"):
            connection.execute(text("UPDATE printers SET has_mismatch = 0 WHERE has_mismatch IS NULL"))
            connection.execute(text("UPDATE printers SET is_enabled = 1 WHERE is_enabled IS NULL"))
            connection.execute(text("UPDATE printers SET is_active = 0 WHERE is_active IS NULL"))
            connection.execute(text("UPDATE printers SET supports_color = 1 WHERE supports_color IS NULL"))
            connection.execute(text("UPDATE printers SET supports_duplex = 1 WHERE supports_duplex IS NULL"))


def migrate():
    sync_schema(engine)
    print("Database tables and missing columns synchronized successfully.")


if __name__ == "__main__":
    migrate()
