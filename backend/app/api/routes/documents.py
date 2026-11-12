from fastapi import APIRouter, Depends, UploadFile, File, status, Request
from app.api.customer_access import customer_access, identity
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db.session import get_db
from app.db.models.document import Document, DocumentStatus
from app.schemas.document import DocumentUploadResponse, DocumentResponse
from app.schemas.common import MessageResponse
from app.services.document_service import document_service
from app.utils.errors import AppException

router = APIRouter(prefix="/api/documents", tags=["Documents"], dependencies=[Depends(customer_access)])

@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Public upload endpoint - no login required.
    Users can upload documents directly to print via station OTP.
    """
    session, user = identity(request, db)
    doc = await document_service.process_and_save_upload(
        db=db,
        file=file,
        user_id=user.id if user else None
    )
    doc.session_token = session
    db.commit()
    return DocumentUploadResponse(
        documentId=doc.id,
        originalFilename=doc.original_filename,
        pages=doc.page_count,
        size=doc.file_size,
        status=doc.status
    )

@router.get("/{document_id}", response_model=DocumentResponse)
def get_document_details(
    document_id: str,
    db: Session = Depends(get_db)
):
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc or doc.status == DocumentStatus.DELETED:
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="NOT_FOUND",
            message="Document not found."
        )

    return doc

@router.get("/{document_id}/preview")
def get_document_preview(
    document_id: str,
    page: int = 1,
    dpi: int = 120,
    db: Session = Depends(get_db)
):
    """
    Renders high-quality preview of PDF or image documents.
    Fast server-side rendering with PyMuPDF for all devices and web.
    """
    from fastapi.responses import Response, FileResponse
    from app.services.storage_service import storage_service
    import fitz
    dpi = max(36, min(dpi, 200))

    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or doc.status == DocumentStatus.DELETED:
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="NOT_FOUND",
            message="Document not found."
        )

    file_path = storage_service.resolve_storage_key(doc.storage_key)
    if not file_path.exists():
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="FILE_NOT_FOUND",
            message="Document file not found on disk."
        )

    mime = (doc.mime_type or "").lower()
    if mime == "application/pdf" or file_path.suffix.lower() == ".pdf":
        try:
            pdf = fitz.open(str(file_path))
            total = len(pdf)
            page_idx = max(0, min(page - 1, total - 1)) if total > 0 else 0
            pdf_page = pdf.load_page(page_idx)
            if pdf_page.rect.width * pdf_page.rect.height * (dpi / 72) ** 2 > 16000000:
                pdf.close()
                raise AppException(413, "PREVIEW_TOO_LARGE", "Page dimensions exceed the preview limit.")
            pix = pdf_page.get_pixmap(dpi=dpi)
            png_bytes = pix.tobytes("png")
            pdf.close()
            return Response(content=png_bytes, media_type="image/png")
        except AppException:
            raise
        except Exception:
            raise AppException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code="PREVIEW_RENDER_ERROR",
                message="Failed to render PDF preview."
            )
    else:
        return FileResponse(str(file_path), media_type=mime or "image/png")


@router.delete("/{document_id}", response_model=MessageResponse)
def delete_document(
    document_id: str,
    db: Session = Depends(get_db)
):
    doc = db.query(Document).filter(Document.id == document_id).first()

    if not doc:
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="NOT_FOUND",
            message="Document not found."
        )

    doc.status = DocumentStatus.CLEANUP_PENDING
    db.commit()
    return MessageResponse(message="Document scheduled for deletion.")
