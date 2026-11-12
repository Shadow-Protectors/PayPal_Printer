from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class RecentPrintJob(BaseModel):
    id: str
    order_id: str
    document_name: str
    user_name: str
    user_email: Optional[str] = None
    department_id: Optional[int] = None
    department_name: str
    printer_name: str
    pages: int
    copies: int
    is_color: bool
    status: str
    created_at: str
    completed_at: Optional[str] = None
    error_message: Optional[str] = None

class DepartmentSummary(BaseModel):
    id: int
    code: str
    name: str
    users_count: int
    printers_count: int
    jobs_count: int
    pages_count: int

class AdminDashboardResponse(BaseModel):
    total_departments: int
    total_users: int
    total_printers: int
    total_print_jobs: int
    total_pages_printed: int
    successful_print_jobs: int
    failed_print_jobs: int
    color_pages: int
    bw_pages: int
    color_jobs: int
    bw_jobs: int
    success_rate: float
    recent_activity: List[RecentPrintJob]
    department_summary: List[DepartmentSummary]

class AdminPrinterItem(BaseModel):
    id: str
    server_id: str
    server_name: Optional[str] = None
    server_status: str
    server_location: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    cups_printer_name: str
    display_name: str
    ip_address: Optional[str] = None
    protocol: str = "Socket"
    device_uri: Optional[str] = None
    model: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    supports_color: bool = True
    supports_duplex: bool = True
    is_enabled: bool = True
    is_active: bool = False
    printer_state: Optional[str] = None
    paper_state: Optional[str] = None
    last_heartbeat: Optional[str] = None
    total_jobs_count: int = 0
    created_at: str
    last_tested_at: Optional[str] = None
    test_status: str = "PENDING"
    test_message: Optional[str] = None
    has_mismatch: Optional[bool] = False
    mismatch_details: Optional[str] = None

class AdminPrinterCreate(BaseModel):
    cups_printer_name: str
    display_name: str
    ip_address: Optional[str] = None
    protocol: str = "Socket"
    device_uri: Optional[str] = None
    server_id: str
    department_id: Optional[int] = None
    location: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    supports_color: bool = True
    supports_duplex: bool = True
    is_enabled: bool = True
    is_active: Optional[bool] = None

class AdminPrinterUpdate(BaseModel):
    display_name: Optional[str] = None
    cups_printer_name: Optional[str] = None
    ip_address: Optional[str] = None
    protocol: Optional[str] = None
    device_uri: Optional[str] = None
    server_id: Optional[str] = None
    department_id: Optional[int] = None
    location: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    supports_color: Optional[bool] = None
    supports_duplex: Optional[bool] = None
    is_enabled: Optional[bool] = None
    is_active: Optional[bool] = None

class PrinterTestConnectionResponse(BaseModel):
    success: bool
    printer_id: str
    is_active: bool
    cups_exists: bool
    reachable: bool
    available: bool
    status: str
    message: str
    tested_at: str

class AdminDiscoveredPrinterItem(BaseModel):
    id: str
    server_id: str
    server_name: Optional[str] = None
    cups_printer_name: str
    ip_address: Optional[str] = None
    device_uri: Optional[str] = None
    reported_status: Optional[str] = None
    reported_jobs: Optional[str] = None
    first_seen: str
    last_seen: str

class AdminPrintAgentItem(BaseModel):
    id: str
    name: str
    location: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    software_version: Optional[str] = None
    status: str
    is_enabled: bool
    last_heartbeat: Optional[str] = None
    printer_count: int = 0
    created_at: str

class AdminAgentCupsPrinterItem(BaseModel):
    cups_printer_name: str
    display_name: str
    device_uri: Optional[str] = None
    ip_address: Optional[str] = None
    status: str = "READY"
    is_mapped: bool = False

class AdminPrintAgentCreate(BaseModel):
    id: Optional[str] = None
    name: str
    location: Optional[str] = None
    department_id: Optional[int] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    software_version: Optional[str] = None
    token: Optional[str] = Field(default=None, min_length=32, max_length=256)

class AdminPrintServerUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    location: Optional[str] = None
    department_id: Optional[int] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    software_version: Optional[str] = None
    is_enabled: Optional[bool] = None


class AdminUserItem(BaseModel):
    id: int
    email: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    roll_number: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    role: str
    is_active: bool
    total_orders: int = 0
    total_pages: int = 0
    total_spent: float = 0.0
    created_at: str

class AdminUserCreate(BaseModel):
    email: str
    full_name: str
    roll_number: Optional[str] = None
    department_id: Optional[int] = None
    role: Optional[str] = "USER"
    is_active: bool = True
    password: Optional[str] = None

class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    roll_number: Optional[str] = None
    department_id: Optional[int] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class PaginatedAdminUsersResponse(BaseModel):
    users: List[AdminUserItem]
    total: int
    page: int
    limit: int
    total_pages: int

class AdminSystemSettings(BaseModel):
    app_name: str
    per_page_rate: float
    base_fee: float
    max_upload_mb: int
    otp_ttl_minutes: int
    max_otp_attempts: int
    max_print_retries: int
    heartbeat_timeout_seconds: int
    email_provider: str
    smtp_host: str
    smtp_user: str
    current_admin_email: str

class AdminSystemSettingsUpdate(BaseModel):
    per_page_rate: Optional[float] = None
    base_fee: Optional[float] = None
    max_upload_mb: Optional[int] = None
    otp_ttl_minutes: Optional[int] = None
    max_otp_attempts: Optional[int] = None
    max_print_retries: Optional[int] = None
    heartbeat_timeout_seconds: Optional[int] = None

class AdminDatabaseStatusResponse(BaseModel):
    status: str
    database_url_masked: str
    environment: str
    latency_ms: float
    total_users: int
    total_departments: int
    total_printers: int
    total_orders: int
    total_print_jobs: int

class UserImportSummary(BaseModel):
    total_rows: int
    created: int
    updated: int
    failed: int
    errors: List[str] = Field(default_factory=list)


class AuditLogItem(BaseModel):
    id: int
    user_id: Optional[int] = None
    actor_type: str
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    meta_data: Optional[Dict[str, Any]] = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)


