import os
import uuid
import tempfile
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
from fastapi import UploadFile, status
from sqlalchemy.orm import Session
from pypdf import PdfReader
from PIL import Image
import threading
from functools import wraps
from starlette.concurrency import run_in_threadpool

from app.config.settings import settings
from app.db.models.document import Document, DocumentStatus
from app.utils.errors import AppException
from app.utils.crypto import compute_file_sha256
from app.utils.file_security import validate_file_content, generate_safe_filename
from app.services.storage_service import storage_service

_inspection_slots = threading.BoundedSemaphore(2)


def bounded_inspection(function):
    @wraps(function)
    def inspect(*args, **kwargs):
        if not _inspection_slots.acquire(blocking=False):
            raise AppException(429, "UPLOAD_BUSY", "Document processing is busy. Please try again shortly.")
        try:
            return function(*args, **kwargs)
        finally:
            _inspection_slots.release()
    return inspect

class DocumentService:
    @staticmethod
    @bounded_inspection
    def inspect_and_count_pages(file_path: Path, mime_type: str) -> int:
        if mime_type == "application/pdf":
            try:
                reader = PdfReader(str(file_path))
                page_count = len(reader.pages)
                if page_count > 1000:
                    raise AppException(413, "DOCUMENT_TOO_LARGE", "PDF exceeds the 1000-page limit.")
                if page_count < 1:
                    raise AppException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        error_code="INVALID_FILE",
                        message="PDF contains no pages."
                    )
                return page_count
            except Exception as e:
                if isinstance(e, AppException):
                    raise e
                raise AppException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_code="INVALID_FILE",
                    message="Failed to parse corrupted PDF."
                )
        elif mime_type in ["image/jpeg", "image/png"]:
            try:
                with Image.open(str(file_path)) as img:
                    if img.width * img.height > 16000000:
                        raise AppException(413, "IMAGE_TOO_LARGE", "Image exceeds the 16 megapixel limit.")
                    img.verify()
                return 1
            except AppException:
                raise
            except Exception:
                raise AppException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_code="INVALID_FILE",
                    message="Failed to parse corrupted image file."
                )
        else:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="UNSUPPORTED_TYPE",
                message=f"Unsupported file format: {mime_type}"
            )

    @classmethod
    async def process_and_save_upload(
        cls,
        db: Session,
        file: UploadFile,
        user_id: Optional[int] = None
    ) -> Document:
        max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
        temp_dir = storage_service.get_temp_dir()
        temp_file_path = temp_dir / f"upload_{uuid.uuid4().hex}.tmp"

        original_filename = file.filename or "unknown_document"
        total_size = 0
        header_bytes = b""

        try:
            with open(temp_file_path, "wb") as f_out:
                # Read first chunk to inspect magic bytes
                first_chunk = await file.read(4096)
                if not first_chunk:
                    raise AppException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        error_code="INVALID_FILE",
                        message="Uploaded file is empty."
                    )
                header_bytes = first_chunk
                total_size += len(first_chunk)
                f_out.write(first_chunk)

                # Read remaining chunks while enforcing file size limit
                while chunk := await file.read(65536):
                    total_size += len(chunk)
                    if total_size > max_bytes:
                        raise AppException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            error_code="FILE_TOO_LARGE",
                            message=f"File exceeds maximum upload size of {settings.MAX_UPLOAD_MB}MB."
                        )
                    f_out.write(chunk)
        except Exception as e:
            if temp_file_path.exists():
                temp_file_path.unlink()
            raise e

        # Validate file content, extension and magic bytes
        validated_mime, extension = validate_file_content(
            header_bytes=header_bytes,
            filename=original_filename,
            content_type=file.content_type
        )

        # Inspect pages and integrity
        try:
            pages = await run_in_threadpool(cls.inspect_and_count_pages, temp_file_path, validated_mime)
        except Exception as e:
            if temp_file_path.exists():
                temp_file_path.unlink()
            raise e

        # Compute SHA-256 hash
        sha256_hash = compute_file_sha256(str(temp_file_path))

        # Generate unique storage details
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        stored_filename = generate_safe_filename(extension)
        sub_folder = str(user_id) if user_id is not None else "public"
        storage_key = f"documents/{sub_folder}/{stored_filename}"

        # Atomically move temp file to user storage
        try:
            storage_service.save_file_atomically(temp_file_path, storage_key)
        except Exception as e:
            if temp_file_path.exists():
                temp_file_path.unlink()
            raise AppException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code="STORAGE_ERROR",
                message="Failed to persist file in storage."
            )

        # Save metadata to DB
        document = Document(
            id=doc_id,
            user_id=user_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            storage_key=storage_key,
            mime_type=validated_mime,
            file_size=total_size,
            sha256=sha256_hash,
            page_count=pages,
            status=DocumentStatus.ACTIVE,
            created_at=datetime.now(timezone.utc)
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        return document

document_service = DocumentService()
