import os
import shutil
from pathlib import Path
from typing import Optional
from app.config.settings import settings
from app.utils.file_security import resolve_safe_storage_path

class StorageService:
    def __init__(self, storage_root: Optional[str] = None):
        configured = storage_root or settings.STORAGE_ROOT
        conf_path = Path(configured)
        if not conf_path.is_absolute():
            self.storage_root = (Path(__file__).resolve().parents[2] / conf_path).resolve()
        else:
            self.storage_root = conf_path.resolve()
        self._ensure_directories()

    def _ensure_directories(self):
        for sub_dir in ["documents", "temp", "quarantine"]:
            (self.storage_root / sub_dir).mkdir(parents=True, exist_ok=True)

    def get_user_document_dir(self, user_id: int) -> Path:
        user_dir = self.storage_root / "documents" / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def get_temp_dir(self) -> Path:
        temp_dir = self.storage_root / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def resolve_storage_key(self, storage_key: str) -> Path:
        primary_path = resolve_safe_storage_path(self.storage_root, storage_key)
        if primary_path.exists():
            return primary_path
        return primary_path

    def save_file_atomically(self, source_temp_path: Path, target_storage_key: str) -> Path:
        """
        Moves a temporary file atomically to its final destination within storage_root.
        Returns the resolved target Path.
        """
        target_path = self.resolve_storage_key(target_storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_temp_path), str(target_path))
        return target_path

    def delete_file(self, storage_key: str) -> bool:
        """
        Safely deletes a file. Returns True if deleted, False if did not exist.
        """
        try:
            target_path = self.resolve_storage_key(storage_key)
            if target_path.exists() and target_path.is_file():
                target_path.unlink()
                return True
            return False
        except Exception:
            return False

storage_service = StorageService()
