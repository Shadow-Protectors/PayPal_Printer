from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from app.db.models.document import DocumentStatus

class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    documentId: str = Field(..., alias="documentId", serialization_alias="documentId")
    originalFilename: str = Field(..., alias="originalFilename", serialization_alias="originalFilename")
    pages: int = Field(..., alias="pages", serialization_alias="pages")
    size: int = Field(..., alias="size", serialization_alias="size")
    status: DocumentStatus

    def __init__(self, **data):
        if "document_id" in data and "documentId" not in data:
            data["documentId"] = data.pop("document_id")
        if "original_filename" in data and "originalFilename" not in data:
            data["originalFilename"] = data.pop("original_filename")
        if "page_count" in data and "pages" not in data:
            data["pages"] = data.pop("page_count")
        if "file_size" in data and "size" not in data:
            data["size"] = data.pop("file_size")
        super().__init__(**data)

class DocumentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: str
    user_id: Optional[int] = None
    original_filename: str
    stored_filename: str
    mime_type: str
    file_size: int
    sha256: str
    page_count: int
    status: DocumentStatus
    created_at: datetime
    expires_at: Optional[datetime] = None
