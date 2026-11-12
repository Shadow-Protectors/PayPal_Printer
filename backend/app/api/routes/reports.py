from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.api.dependencies import get_current_admin
from app.schemas.report import (
    DepartmentReportResponse,
    PaginatedPrintJobsResponse,
    PrintJobDetailResponse,
    PrinterReportItem,
    PrinterSpecificReportResponse,
    CollegeAnalyticsReportResponse,
    ScheduledReportTriggerResponse,
)
from app.services.report_service import report_service
from app.services.export_service import export_service
from app.services.schedule_service import schedule_service

router = APIRouter(prefix="/api/reports", tags=["Department Reports"])

@router.get("/analytics", response_model=CollegeAnalyticsReportResponse)
def get_analytics_report(
    department_id: Optional[int] = Query(None, description="Department ID to filter by, or omit for overall college"),
    printer_id: Optional[str] = Query(None, description="Printer ID filter"),
    period: Optional[str] = Query(None, description="Period preset: today, yesterday, this_week, this_month, last_month, this_year"),
    start_date: Optional[str] = Query(None, description="Custom start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Custom end date (ISO format)"),
    status: Optional[str] = Query(None, description="Job status filter (e.g. COMPLETED, FAILED)"),
    is_color: Optional[bool] = Query(None, description="Color or B&W filter"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Generate modern management analytics report with KPI cards, monthly/daily trends,
    department performance breakdown, printer fleet telemetry, and automated remarks.
    """
    return report_service.generate_analytics_report(
        db=db,
        department_id=department_id,
        printer_id=printer_id,
        start_date=start_date,
        end_date=end_date,
        job_status=status,
        is_color=is_color,
        period_preset=period,
    )

@router.get("/department", response_model=DepartmentReportResponse)
def get_department_report(
    department_id: Optional[int] = Query(None, description="Department ID to filter by, or omit for all"),
    start_date: Optional[str] = Query(None, description="ISO start date filter"),
    end_date: Optional[str] = Query(None, description="ISO end date filter"),
    user_id: Optional[int] = Query(None, description="User ID filter"),
    printer_id: Optional[str] = Query(None, description="Printer ID filter"),
    status: Optional[str] = Query(None, description="Job status filter (e.g. COMPLETED, FAILED)"),
    is_color: Optional[bool] = Query(None, description="Color or B&W filter"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Generate comprehensive department printing report with KPI metrics,
    user-wise statistics, and printer workload utilization.
    Accessible only to authenticated administrators.
    """
    return report_service.generate_department_report(
        db=db,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        printer_id=printer_id,
        job_status=status,
        is_color=is_color,
    )

@router.get("/departments/{department_id}", response_model=DepartmentReportResponse)
def get_single_department_report_shortcut(
    department_id: int,
    start_date: Optional[str] = Query(None, description="ISO start date filter"),
    end_date: Optional[str] = Query(None, description="ISO end date filter"),
    user_id: Optional[int] = Query(None, description="User ID filter"),
    printer_id: Optional[str] = Query(None, description="Printer ID filter"),
    status: Optional[str] = Query(None, description="Job status filter"),
    is_color: Optional[bool] = Query(None, description="Color or B&W filter"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Shortcut endpoint to generate report for a specific department.
    Accessible only to authenticated administrators.
    """
    return report_service.generate_department_report(
        db=db,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        printer_id=printer_id,
        job_status=status,
        is_color=is_color,
    )

@router.get("/printers", response_model=List[PrinterReportItem])
def get_printer_level_reports(
    department_id: Optional[int] = Query(None, description="Department ID to filter by, or omit for all"),
    start_date: Optional[str] = Query(None, description="ISO start date filter"),
    end_date: Optional[str] = Query(None, description="ISO end date filter"),
    status: Optional[str] = Query(None, description="Job status filter (e.g. COMPLETED, FAILED)"),
    is_color: Optional[bool] = Query(None, description="Color or B&W filter"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Retrieve printer-level reports for each registered printer.
    Aggregates total jobs, pages, success rates, reliability, workload share, and revenue.
    Accessible only to authenticated administrators.
    """
    return report_service.generate_printer_level_reports(
        db=db,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
        job_status=status,
        is_color=is_color,
    )

@router.get("/printers/{printer_id}", response_model=PrinterSpecificReportResponse)
def get_printer_specific_report(
    printer_id: str,
    department_id: Optional[int] = Query(None, description="Department ID filter"),
    start_date: Optional[str] = Query(None, description="ISO start date filter"),
    end_date: Optional[str] = Query(None, description="ISO end date filter"),
    status: Optional[str] = Query(None, description="Job status filter"),
    is_color: Optional[bool] = Query(None, description="Color or B&W filter"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Retrieve comprehensive printer-specific report including summary KPI metrics,
    user-level statistics on this printer, and recent job logs.
    Accessible only to authenticated administrators.
    """
    return report_service.generate_printer_specific_report(
        db=db,
        printer_id=printer_id,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
        job_status=status,
        is_color=is_color,
    )

@router.get("/printer", response_model=PrinterSpecificReportResponse)
def get_printer_report_query(
    printer_id: str = Query(..., description="Target printer ID"),
    department_id: Optional[int] = Query(None, description="Department ID filter"),
    start_date: Optional[str] = Query(None, description="ISO start date filter"),
    end_date: Optional[str] = Query(None, description="ISO end date filter"),
    status: Optional[str] = Query(None, description="Job status filter"),
    is_color: Optional[bool] = Query(None, description="Color or B&W filter"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Query parameter alias for printer-specific report.
    Accessible only to authenticated administrators.
    """
    return report_service.generate_printer_specific_report(
        db=db,
        printer_id=printer_id,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
        job_status=status,
        is_color=is_color,
    )

@router.get("/jobs", response_model=PaginatedPrintJobsResponse)
def get_detailed_print_jobs(
    department_id: Optional[int] = Query(None, description="Filter jobs by department ID"),
    user_id: Optional[int] = Query(None, description="Filter jobs by user ID"),
    printer_id: Optional[str] = Query(None, description="Filter jobs by printer ID"),
    status: Optional[str] = Query(None, description="Filter jobs by status"),
    is_color: Optional[bool] = Query(None, description="Filter by color (true) or B&W (false)"),
    start_date: Optional[str] = Query(None, description="ISO start date filter"),
    end_date: Optional[str] = Query(None, description="ISO end date filter"),
    search: Optional[str] = Query(None, description="Search by document name, user, roll no, or job ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    sort_by: str = Query("created_at", description="Sort by field: created_at, pages, amount"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Retrieve paginated, filtered detailed print job logs.
    Supports filtering across departments, users, printers, dates, color modes, and search query.
    Accessible only to authenticated administrators.
    """
    return report_service.get_print_job_logs(
        db=db,
        department_id=department_id,
        user_id=user_id,
        printer_id=printer_id,
        job_status=status,
        is_color=is_color,
        start_date=start_date,
        end_date=end_date,
        search=search,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )

@router.get("/jobs/{job_id}", response_model=PrintJobDetailResponse)
def get_print_job_detail(
    job_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Retrieve full audit and diagnostic details for a specific print job.
    Accessible only to authenticated administrators.
    """
    return report_service.get_print_job_detail(db=db, job_id=job_id)

@router.get("/export/excel")
def export_excel_report(
    department_id: Optional[int] = Query(None),
    period: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    printer_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    is_color: Optional[bool] = Query(None),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Export comprehensive multi-sheet Excel workbook (.xlsx) with formatting and formulas.
    Accessible only to authenticated administrators.
    """
    excel_bytes = export_service.generate_excel_report(
        db=db,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        printer_id=printer_id,
        job_status=status,
        is_color=is_color,
        period_preset=period,
    )
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=achuppori_print_report.xlsx"},
    )

@router.get("/export/pdf")
def export_pdf_report(
    department_id: Optional[int] = Query(None),
    period: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    printer_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    is_color: Optional[bool] = Query(None),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Export formatted printable executive PDF report (.pdf).
    Accessible only to authenticated administrators.
    """
    pdf_bytes = export_service.generate_pdf_report(
        db=db,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        printer_id=printer_id,
        job_status=status,
        is_color=is_color,
        period_preset=period,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=achuppori_print_report.pdf"},
    )

@router.get("/export/csv")
def export_csv_report(
    department_id: Optional[int] = Query(None),
    period: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    printer_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    is_color: Optional[bool] = Query(None),
    report_type: str = Query("department", description="Type of CSV export: department, printers, or jobs"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Export delimited data table as CSV (.csv).
    Accessible only to authenticated administrators.
    """
    csv_bytes = export_service.generate_csv_report(
        db=db,
        department_id=department_id,
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        printer_id=printer_id,
        job_status=status,
        is_color=is_color,
        period_preset=period,
        report_type=report_type,
    )
    filename = f"achuppori_{report_type}_report.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@router.post("/scheduled/trigger", response_model=ScheduledReportTriggerResponse)
def trigger_scheduled_reports(
    period: str = Query("last_month", description="Period to generate reports for: last_month, this_month"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Manually trigger or simulate automatic monthly report generation and dispatch
    to Principal, HODs, Accounts, and System Administrator.
    """
    from app.utils.rate_limit import auth_limiter
    auth_limiter.check(f"report-email:{admin.id}", limit=1, window=60)
    return schedule_service.trigger_scheduled_reports(db=db, period_preset=period)


