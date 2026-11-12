import os
import uuid
from pathlib import Path
from typing import Tuple
from app.utils.errors import AppException
from fastapi import status

SUPPORTED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}

# Magic byte signatures
MAGIC_BYTES = {
    "pdf": b"%PDF-",
    "jpg": b"\xff\xd8\xff",
    "png": b"\x89PNG\r\n\x1a\n",
}

def detect_file_type_from_header(first_bytes: bytes) -> str | None:
    if first_bytes.startswith(MAGIC_BYTES["pdf"]):
        return "application/pdf"
    if first_bytes.startswith(MAGIC_BYTES["png"]):
        return "image/png"
    if first_bytes.startswith(MAGIC_BYTES["jpg"]):
        return "image/jpeg"
    return None

def validate_file_content(header_bytes: bytes, filename: str, content_type: str | None) -> Tuple[str, str]:
    """
    Validates MIME type, extension, and binary header magic bytes.
    Returns (validated_mime, extension)
    """
    detected_mime = detect_file_type_from_header(header_bytes)
    if not detected_mime:
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_FILE",
            message="File content does not match any supported format (PDF, JPG, PNG)."
        )

    # Check extension
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".jpeg":
        ext = ".jpg"

    if detected_mime == "application/pdf" and ext != ".pdf":
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="UNSUPPORTED_TYPE",
            message=f"File extension {ext} does not match detected PDF format."
        )
    elif detected_mime == "image/jpeg" and ext not in [".jpg", ".jpeg"]:
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="UNSUPPORTED_TYPE",
            message=f"File extension {ext} does not match detected JPEG format."
        )
    elif detected_mime == "image/png" and ext != ".png":
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="UNSUPPORTED_TYPE",
            message=f"File extension {ext} does not match detected PNG format."
        )

    return detected_mime, ext

def generate_safe_filename(extension: str) -> str:
    """Generates a cryptographically random, collision-resistant filename."""
    if not extension.startswith("."):
        extension = "." + extension
    return f"{uuid.uuid4().hex}{extension}"

def resolve_safe_storage_path(storage_root: str | Path, storage_key: str) -> Path:
    """
    Resolves storage_root + storage_key and prevents directory traversal attacks.
    Ensures the target resides strictly inside storage_root.
    """
    root_path = Path(storage_root).resolve()
    # Normalize key (strip leading slashes/backslashes)
    clean_key = storage_key.lstrip("/\\")
    target_path = (root_path / clean_key).resolve()

    try:
        target_path.relative_to(root_path)
    except ValueError:
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="PATH_TRAVERSAL_DETECTED",
            message="Invalid storage path detected."
        )

    return target_path
