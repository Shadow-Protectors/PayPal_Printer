from typing import List, Optional
from pydantic import BaseModel
from app.schemas.admin import RecentPrintJob

class DepartmentListItem(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    users_count: int
    printers_count: int
    jobs_count: int
    pages_count: int
    created_at: str

class DepartmentUser(BaseModel):
    id: int
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    roll_number: Optional[str] = None
    role: str
    is_active: bool
    created_at: str

class DepartmentPrinter(BaseModel):
    id: str
    cups_printer_name: str
    display_name: str
    supports_color: bool
    supports_duplex: bool
    is_active: bool
    created_at: str

class DepartmentDetailResponse(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    users_count: int
    printers_count: int
    jobs_count: int
    pages_count: int
    color_pages: int
    bw_pages: int
    created_at: str
    users: List[DepartmentUser]
    printers: List[DepartmentPrinter]
    recent_jobs: List[RecentPrintJob]

class PublicDepartmentItem(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None

class DepartmentCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None

class DepartmentUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
