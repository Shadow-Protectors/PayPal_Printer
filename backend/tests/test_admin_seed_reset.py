"""Exercise destructive maintenance only against a disposable SQLite database."""
from sqlalchemy import create_engine, inspect, select, func, text
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.db.models.user import User, UserRole


def test_reset_removes_legacy_tables_and_seeds_only_admin(tmp_path, monkeypatch):
    import app.db.seed as seed_module
    import app.db.reset_db as reset_module
    from app.config.settings import settings
    engine = create_engine(f"sqlite:///{tmp_path / 'reset.db'}")
    monkeypatch.setattr(seed_module, "engine", engine)
    monkeypatch.setattr(seed_module, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(reset_module, "engine", engine)
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "test-admin@example.com")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "isolated-reset-password")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE obsolete_data (id INTEGER)"))
        conn.execute(text("INSERT INTO obsolete_data VALUES (1)"))
    reset_module.reset_database()
    seed_module.seed()  # Re-running must not create a second user.
    assert "obsolete_data" not in inspect(engine).get_table_names()
    with sessionmaker(bind=engine)() as db:
        users = db.query(User).all()
        assert len(users) == 1 and users[0].role == UserRole.ADMIN
        assert users[0].department_id is None
        for table in Base.metadata.tables.values():
            if table.name != "users":
                assert db.scalar(select(func.count()).select_from(table)) == 0
    engine.dispose()


def test_invalid_credentials_fail_before_deletion(tmp_path, monkeypatch):
    import pytest
    import app.db.reset_db as reset_module
    from app.config.settings import settings
    engine = create_engine(f"sqlite:///{tmp_path / 'preserve.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE valuable_data (id INTEGER)"))
    monkeypatch.setattr(reset_module, "engine", engine)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "")
    with pytest.raises(RuntimeError):
        reset_module.reset_database()
    assert "valuable_data" in inspect(engine).get_table_names()
    engine.dispose()


def test_local_reset_clears_runtime_and_preserves_configuration(tmp_path, monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "scripts/reset_data.py"
    spec = importlib.util.spec_from_file_location("reset_test", script)
    reset = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reset)
    monkeypatch.setattr(reset, "ROOT", tmp_path)
    monkeypatch.delenv("STORAGE_ROOT", raising=False)
    for folder in ("backend", "print-agent"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / ".env").write_text("STORAGE_ROOT=./storage\n")
        (tmp_path / folder / "storage").mkdir()
        (tmp_path / folder / "storage/customer.pdf").write_bytes(b"file")
    calls = []
    monkeypatch.setattr(reset.subprocess, "run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(sys, "argv", ["reset_data.py", "--yes"])
    reset.main()
    assert len(calls) == 1  # Database reset is invoked before local removal.
    assert not (tmp_path / "backend/storage").exists()
    assert not (tmp_path / "print-agent/storage").exists()
    assert (tmp_path / "backend/.env").exists()
    assert (tmp_path / "print-agent/.env").exists()


def test_local_reset_refuses_source_directories(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    import pytest
    script = Path(__file__).resolve().parents[2] / "scripts/reset_data.py"
    spec = importlib.util.spec_from_file_location("reset_safety_test", script)
    reset = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reset)
    monkeypatch.setattr(reset, "ROOT", tmp_path)
    (tmp_path / "backend").mkdir()
    with pytest.raises(RuntimeError):
        reset.validate_paths({tmp_path / "backend"})


def test_data_cleanup_preserves_recreated_sqlite_inside_storage(tmp_path):
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "scripts/reset_data.py"
    spec = importlib.util.spec_from_file_location("reset_db_path_test", script)
    reset = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reset)
    storage = tmp_path / "storage"
    storage.mkdir()
    database = storage / "database.sqlite3"
    database.write_bytes(b"admin-database")
    (storage / "customer.pdf").write_bytes(b"upload")
    reset.clear_path(storage, database.resolve())
    assert database.read_bytes() == b"admin-database"
    assert not (storage / "customer.pdf").exists()
