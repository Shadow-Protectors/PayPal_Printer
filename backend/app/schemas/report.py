from typing import List, Optional
from pydantic import BaseModel

class DepartmentSummaryReport(BaseModel):
    department_id: Optional[int] = None
    department_name: str
    department_code: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    total_jobs: int
    total_pages: int
    successful_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    color_pages: int
    bw_pages: int
    color_jobs: int
    bw_jobs: int
    avg_pages_per_job: float
    total_amount: float

class UserReportStat(BaseModel):
    user_id: Optional[int] = None
    user_name: str
    email: Optional[str] = None
    roll_number: Optional[str] = None
    role: Optional[str] = None
    total_jobs: int
    total_pages: int
    color_pages: int
    bw_pages: int
    success_rate: float

class PrinterUtilizationStat(BaseModel):
    printer_id: str
    printer_name: str
    cups_printer_name: str
    total_jobs: int
    total_pages: int
    utilization_percentage: float
    success_rate: float
    successful_jobs: Optional[int] = 0
    failed_jobs: Optional[int] = 0
    cancelled_jobs: Optional[int] = 0
    color_pages: Optional[int] = 0
    bw_pages: Optional[int] = 0
    total_amount: Optional[float] = 0.0
    status: Optional[str] = "ONLINE"
    is_active: Optional[bool] = True
    department_name: Optional[str] = None
    location: Optional[str] = None

class PrinterReportItem(BaseModel):
    printer_id: str
    printer_name: str
    cups_printer_name: str
    is_active: bool = True
    status: str = "OFFLINE"
    ip_address: Optional[str] = None
    location: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    server_id: Optional[str] = None
    server_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    total_jobs: int = 0
    successful_jobs: int = 0
    failed_jobs: int = 0
    cancelled_jobs: int = 0
    total_pages: int = 0
    color_pages: int = 0
    bw_pages: int = 0
    color_jobs: int = 0
    bw_jobs: int = 0
    avg_pages_per_job: float = 0.0
    success_rate: float = 100.0
    utilization_percentage: float = 0.0
    total_amount: float = 0.0

class DepartmentReportResponse(BaseModel):
    summary: DepartmentSummaryReport
    user_stats: List[UserReportStat]
    printer_stats: List[PrinterUtilizationStat]

class PrintJobDetailResponse(BaseModel):
    id: str
    order_id: str
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    user_roll_number: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    printer_id: Optional[str] = None
    printer_name: Optional[str] = None
    cups_printer_name: Optional[str] = None
    cups_job_id: Optional[str] = None
    document_name: str
    document_id: Optional[str] = None
    file_size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    pages: int
    copies: int
    total_sheets: int
    is_color: bool
    is_duplex: bool
    print_settings: Optional[dict] = None
    amount: float
    currency: str = "INR"
    status: str
    retry_count: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None

class PaginatedPrintJobsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    jobs: List[PrintJobDetailResponse]

class PrinterSpecificReportResponse(BaseModel):
    printer: PrinterReportItem
    summary: PrinterReportItem
    user_stats: List[UserReportStat]
    recent_jobs: List[PrintJobDetailResponse]

# ----------------- Redesigned Management Reporting Schemas -----------------

class AnalyticsTrendPoint(BaseModel):
    period_label: str
    jobs: int = 0
    pages: int = 0
    revenue: float = 0.0
    color_pages: int = 0
    bw_pages: int = 0

class DepartmentPerformanceItem(BaseModel):
    department_id: Optional[int] = None
    department_name: str
    department_code: str
    jobs: int = 0
    pages: int = 0
    revenue: float = 0.0
    color_pages: int = 0
    bw_pages: int = 0
    color_jobs: int = 0
    bw_jobs: int = 0
    active_users: int = 0
    printers_count: int = 0
    workload_share_pct: float = 0.0
    revenue_share_pct: float = 0.0

class UserDemographicsSummary(BaseModel):
    total_active_users: int = 0
    faculty_count: int = 0
    student_count: int = 0
    guest_count: int = 0
    avg_pages_per_user: float = 0.0
    avg_jobs_per_user: float = 0.0

class AutomatedRemarks(BaseModel):
    volume_observation: str
    color_ratio_observation: str
    revenue_observation: str
    fleet_observation: str
    department_observation: str
    key_recommendations: List[str]

class CollegeAnalyticsReportResponse(BaseModel):
    report_title: str
    scope: str
    period_label: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    summary: DepartmentSummaryReport
    monthly_trends: List[AnalyticsTrendPoint]
    daily_trends: List[AnalyticsTrendPoint]
    weekly_trends: List[AnalyticsTrendPoint]
    department_performance: List[DepartmentPerformanceItem]
    printer_stats: List[PrinterUtilizationStat]
    user_demographics: UserDemographicsSummary
    remarks: AutomatedRemarks
    active_printers_count: int
    active_departments_count: int
    user_stats: Optional[List[UserReportStat]] = None

class ScheduledReportTriggerResponse(BaseModel):
    success: bool
    dispatched_count: int
    recipients: List[dict]
    generated_at: str
