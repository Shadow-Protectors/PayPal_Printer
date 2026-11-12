from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel

T = TypeVar("T")

class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Any] = None

class MessageResponse(BaseModel):
    message: str
