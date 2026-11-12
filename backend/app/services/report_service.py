from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.db.models.department import Department
from app.db.models.user import User
from app.db.models.printer import Printer
from app.db.models.order import Order
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.document import Document
from app.db.models.print_server import PrintServer
from app.schemas.report import (
    DepartmentReportResponse,
    DepartmentSummaryReport,
    UserReportStat,
    PrinterUtilizationStat,
    PrinterReportItem,
    PrinterSpecificReportResponse,
    PrintJobDetailResponse,
    PaginatedPrintJobsResponse,
    AnalyticsTrendPoint,
    DepartmentPerformanceItem,
    UserDemographicsSummary,
    AutomatedRemarks,
    CollegeAnalyticsReportResponse,
)
from app.utils.errors import AppException
from fastapi import status

class ReportService:
    @staticmethod
    def generate_department_report(
        db: Session,
        department_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user_id: Optional[int] = None,
        printer_id: Optional[str] = None,
        job_status: Optional[str] = None,
        is_color: Optional[bool] = None,
    ) -> DepartmentReportResponse:
        dept = None
        dept_name = "All Departments"
        dept_code = "ALL"

        if department_id is not None:
            dept = db.query(Department).filter(Department.id == department_id).first()
            if not dept:
                raise AppException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_code="DEPARTMENT_NOT_FOUND",
                    message=f"Department with ID {department_id} not found."
                )
            dept_name = dept.name
            dept_code = dept.code
        elif printer_id:
            filtered_p = db.query(Printer).filter(Printer.id == printer_id).first()
            if filtered_p:
                dept_name = f"Printer: {filtered_p.display_name}"
                dept_code = filtered_p.cups_printer_name

        # Base query joining PrintJob, Order, User, Printer, Document
        query = (
            db.query(PrintJob, Order, Document, User, Printer)
            .join(Order, Order.id == PrintJob.order_id)
            .outerjoin(Document, Document.id == Order.document_id)
            .outerjoin(User, User.id == Order.user_id)
            .outerjoin(Printer, Printer.id == PrintJob.printer_id)
        )

        # Department filter
        if dept:
            query = query.filter(
                or_(
                    User.department_id == dept.id,
                    Order.department == dept.name,
                    Order.department == dept.code,
                )
            )

        # Date range filter
        parsed_start = None
        parsed_end = None
        if start_date:
            try:
                parsed_start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                if parsed_start.tzinfo is not None:
                    parsed_start = parsed_start.astimezone(timezone.utc).replace(tzinfo=None)
                query = query.filter(PrintJob.created_at >= parsed_start)
            except ValueError:
                raise AppException(422, "INVALID_REPORT_DATE", "Use an ISO date or timestamp.")

        if end_date:
            try:
                parsed_end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                if parsed_end.tzinfo is not None:
                    parsed_end = parsed_end.astimezone(timezone.utc).replace(tzinfo=None)
                query = query.filter(PrintJob.created_at <= parsed_end)
            except ValueError:
                raise AppException(422, "INVALID_REPORT_DATE", "Use an ISO date or timestamp.")

        # User filter
        if user_id is not None:
            query = query.filter(Order.user_id == user_id)

        # Printer filter
        if printer_id:
            query = query.filter(PrintJob.printer_id == printer_id)

        # Job Status filter
        if job_status and job_status.strip():
            st_clean = job_status.strip().upper()
            query = query.filter(PrintJob.status == st_clean)

        records = query.order_by(PrintJob.created_at.desc()).all()

        # Aggregation variables
        total_jobs = 0
        total_pages = 0
        successful_jobs = 0
        failed_jobs = 0
        cancelled_jobs = 0
        color_pages = 0
        bw_pages = 0
        color_jobs = 0
        bw_jobs = 0
        total_amount = 0.0

        user_data_map: Dict[int, Dict[str, Any]] = {}
        printer_data_map: Dict[str, Dict[str, Any]] = {}

        for job, order, doc, user, printer in records:
            # Color/BW filter if requested
            job_is_color = False
            if order and order.print_settings:
                c_val = order.print_settings.get("colour", order.print_settings.get("color", False))
                if isinstance(c_val, str):
                    job_is_color = c_val.lower() in ["true", "color", "colour", "1"]
                else:
                    job_is_color = bool(c_val)

            if is_color is not None and job_is_color != is_color:
                continue

            total_jobs += 1

            # Job status evaluation
            st_val = job.status.value if hasattr(job.status, "value") else str(job.status)
            is_success = st_val == PrintJobStatus.COMPLETED.value
            is_failed = st_val in [PrintJobStatus.FAILED.value, PrintJobStatus.FINAL_FAILED.value]
            is_cancelled = st_val == PrintJobStatus.CANCELLED.value

            if is_success:
                successful_jobs += 1
            elif is_failed:
                failed_jobs += 1
            elif is_cancelled:
                cancelled_jobs += 1

            # Pages calculation
            copies = order.copies if (order and order.copies) else 1
            pages_per_copy = (order.total_pages if order and order.total_pages else (doc.page_count if doc and doc.page_count else 1))
            job_pages = pages_per_copy * copies
            total_pages += job_pages

            if order and order.amount:
                total_amount += float(order.amount)

            if job_is_color:
                color_jobs += 1
                color_pages += job_pages
            else:
                bw_jobs += 1
                bw_pages += job_pages

            # User aggregation
            u_key = user.id if user else 0
            if u_key not in user_data_map:
                user_data_map[u_key] = {
                    "user_id": user.id if user else None,
                    "user_name": (user.full_name or user.email) if user else "Walk-in Guest",
                    "email": user.email if user else None,
                    "roll_number": user.roll_number if user else None,
                    "total_jobs": 0,
                    "successful_jobs": 0,
                    "total_pages": 0,
                    "color_pages": 0,
                    "bw_pages": 0,
                }
            user_data_map[u_key]["total_jobs"] += 1
            user_data_map[u_key]["total_pages"] += job_pages
            if is_success:
                user_data_map[u_key]["successful_jobs"] += 1
            if job_is_color:
                user_data_map[u_key]["color_pages"] += job_pages
            else:
                user_data_map[u_key]["bw_pages"] += job_pages

            # Printer aggregation
            p_id = printer.id if printer else (
                order.print_settings.get("printer_id", "unassigned") if order and order.print_settings else "unassigned"
            )
            p_name = printer.display_name if printer else (
                order.print_settings.get("printer_name", "Station Printer") if order and order.print_settings else "Station Printer"
            )
            cups_name = printer.cups_printer_name if printer else (
                order.print_settings.get("cups_printer_name", "default_cups") if order and order.print_settings else "default_cups"
            )

            if p_id not in printer_data_map:
                printer_data_map[p_id] = {
                    "printer_id": p_id,
                    "printer_name": p_name,
                    "cups_printer_name": cups_name,
                    "total_jobs": 0,
                    "successful_jobs": 0,
                    "failed_jobs": 0,
                    "cancelled_jobs": 0,
                    "total_pages": 0,
                    "color_pages": 0,
                    "bw_pages": 0,
                    "total_amount": 0.0,
                    "status": printer.printer_status if (printer and printer.printer_status) else "ONLINE",
                    "is_active": printer.is_active if (printer and printer.is_active is not None) else True,
                    "location": printer.location if printer else None,
                }
            printer_data_map[p_id]["total_jobs"] += 1
            printer_data_map[p_id]["total_pages"] += job_pages
            if order and order.amount:
                printer_data_map[p_id]["total_amount"] += float(order.amount)

            if is_success:
                printer_data_map[p_id]["successful_jobs"] += 1
            elif is_failed:
                printer_data_map[p_id]["failed_jobs"] += 1
            elif is_cancelled:
                printer_data_map[p_id]["cancelled_jobs"] += 1

            if job_is_color:
                printer_data_map[p_id]["color_pages"] += job_pages
            else:
                printer_data_map[p_id]["bw_pages"] += job_pages

        # Calculate averages and lists
        avg_pages = round(total_pages / total_jobs, 2) if total_jobs > 0 else 0.0

        user_stats: List[UserReportStat] = []
        for u in user_data_map.values():
            s_rate = round(u["successful_jobs"] / u["total_jobs"] * 100, 1) if u["total_jobs"] > 0 else 100.0
            user_stats.append(
                UserReportStat(
                    user_id=u["user_id"],
                    user_name=u["user_name"],
                    email=u["email"],
                    roll_number=u["roll_number"],
                    total_jobs=u["total_jobs"],
                    total_pages=u["total_pages"],
                    color_pages=u["color_pages"],
                    bw_pages=u["bw_pages"],
                    success_rate=s_rate,
                )
            )
        user_stats.sort(key=lambda x: x.total_pages, reverse=True)

        printer_stats: List[PrinterUtilizationStat] = []
        for p in printer_data_map.values():
            p_util = round(p["total_pages"] / total_pages * 100, 1) if total_pages > 0 else 0.0
            s_rate = round(p["successful_jobs"] / p["total_jobs"] * 100, 1) if p["total_jobs"] > 0 else 100.0
            printer_stats.append(
                PrinterUtilizationStat(
                    printer_id=p["printer_id"],
                    printer_name=p["printer_name"],
                    cups_printer_name=p["cups_printer_name"],
                    total_jobs=p["total_jobs"],
                    total_pages=p["total_pages"],
                    utilization_percentage=p_util,
                    success_rate=s_rate,
                    successful_jobs=p.get("successful_jobs", 0),
                    failed_jobs=p.get("failed_jobs", 0),
                    cancelled_jobs=p.get("cancelled_jobs", 0),
                    color_pages=p.get("color_pages", 0),
                    bw_pages=p.get("bw_pages", 0),
                    total_amount=round(p.get("total_amount", 0.0), 2),
                    status=p.get("status", "ONLINE"),
                    is_active=p.get("is_active", True),
                    location=p.get("location"),
                )
            )
        printer_stats.sort(key=lambda x: x.total_pages, reverse=True)

        summary = DepartmentSummaryReport(
            department_id=dept.id if dept else None,
            department_name=dept_name,
            department_code=dept_code,
            start_date=start_date,
            end_date=end_date,
            total_jobs=total_jobs,
            total_pages=total_pages,
            successful_jobs=successful_jobs,
            failed_jobs=failed_jobs,
            cancelled_jobs=cancelled_jobs,
            color_pages=color_pages,
            bw_pages=bw_pages,
            color_jobs=color_jobs,
            bw_jobs=bw_jobs,
            avg_pages_per_job=avg_pages,
            total_amount=round(total_amount, 2),
        )

        return DepartmentReportResponse(
            summary=summary,
            user_stats=user_stats,
            printer_stats=printer_stats,
        )

    @staticmethod
    def _format_job_detail(
        job: PrintJob,
        order: Optional[Order],
        doc: Optional[Document],
        user: Optional[User],
        printer: Optional[Printer],
        dept: Optional[Department] = None,
    ) -> PrintJobDetailResponse:
        is_job_color = False
        is_duplex = False
        print_settings_dict = {}
        if order and order.print_settings:
            if isinstance(order.print_settings, dict):
                print_settings_dict = order.print_settings
            c_val = print_settings_dict.get("colour", print_settings_dict.get("color", False))
            if isinstance(c_val, str):
                is_job_color = c_val.lower() in ["true", "color", "colour", "1"]
            else:
                is_job_color = bool(c_val)
            sides = str(print_settings_dict.get("sides", "one-sided")).lower()
            is_duplex = "two" in sides or "duplex" in sides

        pages = order.total_pages if order and order.total_pages else (doc.page_count if doc else 1)
        copies = order.copies if order and order.copies else 1
        total_sheets = pages * copies
        if is_duplex:
            total_sheets = ((pages + 1) // 2) * copies

        dept_id = dept.id if dept else (user.department_id if user else None)
        dept_name = dept.name if dept else (user.department if user and user.department else (order.department if order and order.department else "General"))

        st_val = job.status.value if hasattr(job.status, "value") else str(job.status)

        return PrintJobDetailResponse(
            id=job.id,
            order_id=job.order_id,
            user_id=user.id if user else (order.user_id if order else None),
            user_name=user.full_name if user and user.full_name else (user.email if user and user.email else "Customer"),
            user_email=user.email if user else None,
            user_roll_number=user.roll_number if user else (order.roll_number if order else None),
            department_id=dept_id,
            department_name=dept_name,
            printer_id=printer.id if printer else job.printer_id,
            printer_name=printer.display_name if printer else "Local Station",
            cups_printer_name=printer.cups_printer_name if printer else "Default Queue",
            cups_job_id=job.cups_job_id,
            document_name=doc.original_filename if doc else "Document",
            document_id=doc.id if doc else (order.document_id if order else None),
            file_size_bytes=doc.file_size if doc else None,
            mime_type=doc.mime_type if doc else None,
            pages=pages,
            copies=copies,
            total_sheets=total_sheets,
            is_color=is_job_color,
            is_duplex=is_duplex,
            print_settings=print_settings_dict,
            amount=float(order.amount) if order and order.amount is not None else 0.0,
            currency=order.currency if order and order.currency else "INR",
            status=st_val,
            retry_count=job.retry_count or 0,
            error_code=job.error_code,
            error_message=job.error_message,
            created_at=job.created_at.strftime("%Y-%m-%d %H:%M:%S") if job.created_at else "",
            completed_at=(job.completed_at or (job.updated_at if st_val in [PrintJobStatus.COMPLETED.value, PrintJobStatus.CANCELLED.value, PrintJobStatus.FAILED.value, PrintJobStatus.FINAL_FAILED.value] else None)).strftime("%Y-%m-%d %H:%M:%S") if (job.completed_at or (job.updated_at if st_val in [PrintJobStatus.COMPLETED.value, PrintJobStatus.CANCELLED.value, PrintJobStatus.FAILED.value, PrintJobStatus.FINAL_FAILED.value] else None)) else None,
        )

    @staticmethod
    def get_print_job_logs(
        db: Session,
        department_id: Optional[int] = None,
        user_id: Optional[int] = None,
        printer_id: Optional[str] = None,
        job_status: Optional[str] = None,
        is_color: Optional[bool] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> PaginatedPrintJobsResponse:
        dept = None
        if department_id is not None:
            dept = db.query(Department).filter(Department.id == department_id).first()

        query = (
            db.query(PrintJob, Order, Document, User, Printer, Department)
            .join(Order, Order.id == PrintJob.order_id)
            .outerjoin(Document, Document.id == Order.document_id)
            .outerjoin(User, User.id == Order.user_id)
            .outerjoin(Printer, Printer.id == PrintJob.printer_id)
            .outerjoin(Department, Department.id == User.department_id)
        )

        if dept:
            query = query.filter(
                or_(
                    User.department_id == dept.id,
                    Order.department == dept.name,
                    Order.department == dept.code,
                )
            )

        if start_date:
            try:
                parsed_start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                if parsed_start.tzinfo is not None:
                    parsed_start = parsed_start.astimezone(timezone.utc).replace(tzinfo=None)
                query = query.filter(PrintJob.created_at >= parsed_start)
            except ValueError:
                raise AppException(422, "INVALID_REPORT_DATE", "Use an ISO date or timestamp.")

        if end_date:
            try:
                parsed_end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                if parsed_end.tzinfo is not None:
                    parsed_end = parsed_end.astimezone(timezone.utc).replace(tzinfo=None)
                query = query.filter(PrintJob.created_at <= parsed_end)
            except ValueError:
                raise AppException(422, "INVALID_REPORT_DATE", "Use an ISO date or timestamp.")

        if user_id is not None:
            query = query.filter(Order.user_id == user_id)

        if printer_id:
            query = query.filter(PrintJob.printer_id == printer_id)

        if job_status and job_status.strip():
            query = query.filter(PrintJob.status == job_status.strip().upper())

        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    PrintJob.id.ilike(term),
                    PrintJob.cups_job_id.ilike(term),
                    Order.id.ilike(term),
                    Document.original_filename.ilike(term),
                    User.full_name.ilike(term),
                    User.email.ilike(term),
                    User.roll_number.ilike(term),
                    Order.roll_number.ilike(term),
                    Printer.display_name.ilike(term),
                    Department.name.ilike(term),
                )
            )

        # Ordering
        if sort_by == "pages":
            order_col = Order.total_pages.asc() if sort_order.lower() == "asc" else Order.total_pages.desc()
        elif sort_by == "amount":
            order_col = Order.amount.asc() if sort_order.lower() == "asc" else Order.amount.desc()
        else:
            order_col = PrintJob.created_at.asc() if sort_order.lower() == "asc" else PrintJob.created_at.desc()

        records = query.order_by(order_col).all()

        formatted_jobs: List[PrintJobDetailResponse] = []
        for job, order, doc, user, printer, d in records:
            job_resp = ReportService._format_job_detail(job, order, doc, user, printer, d)
            if is_color is not None and job_resp.is_color != is_color:
                continue
            formatted_jobs.append(job_resp)

        total = len(formatted_jobs)
        page = max(1, page)
        page_size = max(1, min(5000, page_size))
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paged_jobs = formatted_jobs[start_idx:end_idx]

        return PaginatedPrintJobsResponse(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            jobs=paged_jobs,
        )

    @staticmethod
    def get_print_job_detail(db: Session, job_id: str) -> PrintJobDetailResponse:
        record = (
            db.query(PrintJob, Order, Document, User, Printer, Department)
            .join(Order, Order.id == PrintJob.order_id)
            .outerjoin(Document, Document.id == Order.document_id)
            .outerjoin(User, User.id == Order.user_id)
            .outerjoin(Printer, Printer.id == PrintJob.printer_id)
            .outerjoin(Department, Department.id == User.department_id)
            .filter(PrintJob.id == job_id)
            .first()
        )
        if not record:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="PRINT_JOB_NOT_FOUND",
                message=f"Print job '{job_id}' not found.",
            )
        job, order, doc, user, printer, dept = record
        return ReportService._format_job_detail(job, order, doc, user, printer, dept)

    @staticmethod
    def generate_printer_level_reports(
        db: Session,
        department_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        job_status: Optional[str] = None,
        is_color: Optional[bool] = None,
    ) -> List[PrinterReportItem]:
        """
        Generates printer-level reports for each printer registered in the system,
        aggregating workload, page counts, reliability and billing metrics.
        """
        p_query = (
            db.query(Printer, Department, PrintServer)
            .outerjoin(Department, Department.id == Printer.department_id)
            .outerjoin(PrintServer, PrintServer.id == Printer.server_id)
        )
        if department_id is not None:
            p_query = p_query.filter(Printer.department_id == department_id)
        printers_list = p_query.all()

        query = (
            db.query(PrintJob, Order, Document, User, Printer)
            .join(Order, Order.id == PrintJob.order_id)
            .outerjoin(Document, Document.id == Order.document_id)
            .outerjoin(User, User.id == Order.user_id)
            .outerjoin(Printer, Printer.id == PrintJob.printer_id)
        )
        if department_id is not None:
            dept = db.query(Department).filter(Department.id == department_id).first()
            if dept:
                query = query.filter(
                    or_(
                        Printer.department_id == dept.id,
                        User.department_id == dept.id,
                        Order.department == dept.name,
                        Order.department == dept.code,
                    )
                )

        parsed_start = None
        parsed_end = None
        if start_date:
            try:
                parsed_start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                if parsed_start.tzinfo is not None:
                    parsed_start = parsed_start.astimezone(timezone.utc).replace(tzinfo=None)
                query = query.filter(PrintJob.created_at >= parsed_start)
            except ValueError:
                raise AppException(422, "INVALID_REPORT_DATE", "Use an ISO date or timestamp.")

        if end_date:
            try:
                parsed_end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                if parsed_end.tzinfo is not None:
                    parsed_end = parsed_end.astimezone(timezone.utc).replace(tzinfo=None)
                query = query.filter(PrintJob.created_at <= parsed_end)
            except ValueError:
                raise AppException(422, "INVALID_REPORT_DATE", "Use an ISO date or timestamp.")

        if job_status and job_status.strip():
            st_clean = job_status.strip().upper()
            query = query.filter(PrintJob.status == st_clean)

        records = query.all()

        system_total_pages = 0
        job_stats_by_printer: Dict[str, Dict[str, Any]] = {}

        for job, order, doc, user, printer in records:
            job_is_color = False
            if order and order.print_settings:
                c_val = order.print_settings.get("colour", order.print_settings.get("color", False))
                if isinstance(c_val, str):
                    job_is_color = c_val.lower() in ["true", "color", "colour", "1"]
                else:
                    job_is_color = bool(c_val)

            if is_color is not None and job_is_color != is_color:
                continue

            copies = order.copies if (order and order.copies) else 1
            pages_per_copy = (order.total_pages if order and order.total_pages else (doc.page_count if doc and doc.page_count else 1))
            job_pages = pages_per_copy * copies
            system_total_pages += job_pages

            p_id = printer.id if printer else (
                order.print_settings.get("printer_id", "unassigned") if order and order.print_settings else "unassigned"
            )

            if p_id not in job_stats_by_printer:
                job_stats_by_printer[p_id] = {
                    "total_jobs": 0,
                    "successful_jobs": 0,
                    "failed_jobs": 0,
                    "cancelled_jobs": 0,
                    "total_pages": 0,
                    "color_pages": 0,
                    "bw_pages": 0,
                    "color_jobs": 0,
                    "bw_jobs": 0,
                    "total_amount": 0.0,
                }

            st_val = job.status.value if hasattr(job.status, "value") else str(job.status)
            is_success = st_val == PrintJobStatus.COMPLETED.value
            is_failed = st_val in [PrintJobStatus.FAILED.value, PrintJobStatus.FINAL_FAILED.value]
            is_cancelled = st_val == PrintJobStatus.CANCELLED.value

            stats = job_stats_by_printer[p_id]
            stats["total_jobs"] += 1
            stats["total_pages"] += job_pages
            if order and order.amount:
                stats["total_amount"] += float(order.amount)

            if is_success:
                stats["successful_jobs"] += 1
            elif is_failed:
                stats["failed_jobs"] += 1
            elif is_cancelled:
                stats["cancelled_jobs"] += 1

            if job_is_color:
                stats["color_jobs"] += 1
                stats["color_pages"] += job_pages
            else:
                stats["bw_jobs"] += 1
                stats["bw_pages"] += job_pages

        printer_report_items: List[PrinterReportItem] = []
        handled_printer_ids = set()

        for printer, dept, server in printers_list:
            handled_printer_ids.add(printer.id)
            stats = job_stats_by_printer.get(printer.id, {
                "total_jobs": 0,
                "successful_jobs": 0,
                "failed_jobs": 0,
                "cancelled_jobs": 0,
                "total_pages": 0,
                "color_pages": 0,
                "bw_pages": 0,
                "color_jobs": 0,
                "bw_jobs": 0,
                "total_amount": 0.0,
            })

            t_jobs = stats["total_jobs"]
            t_pages = stats["total_pages"]
            s_jobs = stats["successful_jobs"]
            s_rate = round((s_jobs / t_jobs * 100), 1) if t_jobs > 0 else 100.0
            avg_p = round((t_pages / t_jobs), 2) if t_jobs > 0 else 0.0
            util_pct = round((t_pages / system_total_pages * 100), 1) if system_total_pages > 0 else 0.0

            printer_report_items.append(
                PrinterReportItem(
                    printer_id=printer.id,
                    printer_name=printer.display_name,
                    cups_printer_name=printer.cups_printer_name,
                    is_active=printer.is_active if printer.is_active is not None else True,
                    status=printer.printer_status or ("ONLINE" if printer.is_active else "OFFLINE"),
                    ip_address=printer.ip_address,
                    location=printer.location,
                    department_id=printer.department_id,
                    department_name=dept.name if dept else None,
                    server_id=printer.server_id,
                    server_name=server.name if server else None,
                    start_date=start_date,
                    end_date=end_date,
                    total_jobs=t_jobs,
                    successful_jobs=s_jobs,
                    failed_jobs=stats["failed_jobs"],
                    cancelled_jobs=stats["cancelled_jobs"],
                    total_pages=t_pages,
                    color_pages=stats["color_pages"],
                    bw_pages=stats["bw_pages"],
                    color_jobs=stats["color_jobs"],
                    bw_jobs=stats["bw_jobs"],
                    avg_pages_per_job=avg_p,
                    success_rate=s_rate,
                    utilization_percentage=util_pct,
                    total_amount=round(stats["total_amount"], 2),
                )
            )

        for p_id, stats in job_stats_by_printer.items():
            if p_id not in handled_printer_ids and p_id != "unassigned":
                t_jobs = stats["total_jobs"]
                t_pages = stats["total_pages"]
                s_jobs = stats["successful_jobs"]
                s_rate = round((s_jobs / t_jobs * 100), 1) if t_jobs > 0 else 100.0
                avg_p = round((t_pages / t_jobs), 2) if t_jobs > 0 else 0.0
                util_pct = round((t_pages / system_total_pages * 100), 1) if system_total_pages > 0 else 0.0

                printer_report_items.append(
                    PrinterReportItem(
                        printer_id=p_id,
                        printer_name=p_id,
                        cups_printer_name=p_id,
                        is_active=False,
                        status="OFFLINE",
                        start_date=start_date,
                        end_date=end_date,
                        total_jobs=t_jobs,
                        successful_jobs=s_jobs,
                        failed_jobs=stats["failed_jobs"],
                        cancelled_jobs=stats["cancelled_jobs"],
                        total_pages=t_pages,
                        color_pages=stats["color_pages"],
                        bw_pages=stats["bw_pages"],
                        color_jobs=stats["color_jobs"],
                        bw_jobs=stats["bw_jobs"],
                        avg_pages_per_job=avg_p,
                        success_rate=s_rate,
                        utilization_percentage=util_pct,
                        total_amount=round(stats["total_amount"], 2),
                    )
                )

        printer_report_items.sort(key=lambda x: (x.total_jobs, x.total_pages), reverse=True)
        return printer_report_items

    @staticmethod
    def generate_printer_specific_report(
        db: Session,
        printer_id: str,
        department_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        job_status: Optional[str] = None,
        is_color: Optional[bool] = None,
    ) -> PrinterSpecificReportResponse:
        """
        Generates comprehensive printer-specific report including summary metrics,
        user-level breakdown on this printer, and recent job logs.
        """
        printer_record = (
            db.query(Printer, Department, PrintServer)
            .outerjoin(Department, Department.id == Printer.department_id)
            .outerjoin(PrintServer, PrintServer.id == Printer.server_id)
            .filter(Printer.id == printer_id)
            .first()
        )
        if not printer_record:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="PRINTER_NOT_FOUND",
                message=f"Printer with ID '{printer_id}' not found."
            )

        printer, dept, server = printer_record

        query = (
            db.query(PrintJob, Order, Document, User, Printer)
            .join(Order, Order.id == PrintJob.order_id)
            .outerjoin(Document, Document.id == Order.document_id)
            .outerjoin(User, User.id == Order.user_id)
            .outerjoin(Printer, Printer.id == PrintJob.printer_id)
            .filter(PrintJob.printer_id == printer_id)
        )

        if department_id is not None:
            query = query.filter(
                or_(
                    User.department_id == department_id,
                    Printer.department_id == department_id,
                )
            )

        parsed_start = None
        parsed_end = None
        if start_date:
            try:
                parsed_start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                if parsed_start.tzinfo is not None:
                    parsed_start = parsed_start.astimezone(timezone.utc).replace(tzinfo=None)
                query = query.filter(PrintJob.created_at >= parsed_start)
            except ValueError:
                raise AppException(422, "INVALID_REPORT_DATE", "Use an ISO date or timestamp.")

        if end_date:
            try:
                parsed_end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                if parsed_end.tzinfo is not None:
                    parsed_end = parsed_end.astimezone(timezone.utc).replace(tzinfo=None)
                query = query.filter(PrintJob.created_at <= parsed_end)
            except ValueError:
                raise AppException(422, "INVALID_REPORT_DATE", "Use an ISO date or timestamp.")

        if job_status and job_status.strip():
            st_clean = job_status.strip().upper()
            query = query.filter(PrintJob.status == st_clean)

        records = query.order_by(PrintJob.created_at.desc()).all()

        total_jobs = 0
        successful_jobs = 0
        failed_jobs = 0
        cancelled_jobs = 0
        total_pages = 0
        color_pages = 0
        bw_pages = 0
        color_jobs = 0
        bw_jobs = 0
        total_amount = 0.0

        user_data_map: Dict[int, Dict[str, Any]] = {}
        recent_jobs: List[PrintJobDetailResponse] = []

        for job, order, doc, user, p in records:
            job_is_color = False
            if order and order.print_settings:
                c_val = order.print_settings.get("colour", order.print_settings.get("color", False))
                if isinstance(c_val, str):
                    job_is_color = c_val.lower() in ["true", "color", "colour", "1"]
                else:
                    job_is_color = bool(c_val)

            if is_color is not None and job_is_color != is_color:
                continue

            total_jobs += 1
            copies = order.copies if (order and order.copies) else 1
            pages_per_copy = (order.total_pages if order and order.total_pages else (doc.page_count if doc and doc.page_count else 1))
            job_pages = pages_per_copy * copies
            total_pages += job_pages

            if order and order.amount:
                total_amount += float(order.amount)

            st_val = job.status.value if hasattr(job.status, "value") else str(job.status)
            is_success = st_val == PrintJobStatus.COMPLETED.value
            is_failed = st_val in [PrintJobStatus.FAILED.value, PrintJobStatus.FINAL_FAILED.value]
            is_cancelled = st_val == PrintJobStatus.CANCELLED.value

            if is_success:
                successful_jobs += 1
            elif is_failed:
                failed_jobs += 1
            elif is_cancelled:
                cancelled_jobs += 1

            if job_is_color:
                color_jobs += 1
                color_pages += job_pages
            else:
                bw_jobs += 1
                bw_pages += job_pages

            u_key = user.id if user else 0
            if u_key not in user_data_map:
                user_data_map[u_key] = {
                    "user_id": user.id if user else None,
                    "user_name": (user.full_name or user.email) if user else "Walk-in Guest",
                    "email": user.email if user else None,
                    "roll_number": user.roll_number if user else None,
                    "total_jobs": 0,
                    "successful_jobs": 0,
                    "total_pages": 0,
                    "color_pages": 0,
                    "bw_pages": 0,
                }
            user_data_map[u_key]["total_jobs"] += 1
            user_data_map[u_key]["total_pages"] += job_pages
            if is_success:
                user_data_map[u_key]["successful_jobs"] += 1
            if job_is_color:
                user_data_map[u_key]["color_pages"] += job_pages
            else:
                user_data_map[u_key]["bw_pages"] += job_pages

            if len(recent_jobs) < 50:
                recent_jobs.append(ReportService._format_job_detail(job, order, doc, user, printer, dept))

        success_rate = round(successful_jobs / total_jobs * 100, 1) if total_jobs > 0 else 100.0
        avg_pages = round(total_pages / total_jobs, 2) if total_jobs > 0 else 0.0

        user_stats: List[UserReportStat] = []
        for u in user_data_map.values():
            s_rate = round(u["successful_jobs"] / u["total_jobs"] * 100, 1) if u["total_jobs"] > 0 else 100.0
            user_stats.append(
                UserReportStat(
                    user_id=u["user_id"],
                    user_name=u["user_name"],
                    email=u["email"],
                    roll_number=u["roll_number"],
                    total_jobs=u["total_jobs"],
                    total_pages=u["total_pages"],
                    color_pages=u["color_pages"],
                    bw_pages=u["bw_pages"],
                    success_rate=s_rate,
                )
            )
        user_stats.sort(key=lambda x: x.total_pages, reverse=True)

        summary_item = PrinterReportItem(
            printer_id=printer.id,
            printer_name=printer.display_name,
            cups_printer_name=printer.cups_printer_name,
            is_active=printer.is_active if printer.is_active is not None else True,
            status=printer.printer_status or ("ONLINE" if printer.is_active else "OFFLINE"),
            ip_address=printer.ip_address,
            location=printer.location,
            department_id=printer.department_id,
            department_name=dept.name if dept else None,
            server_id=printer.server_id,
            server_name=server.name if server else None,
            start_date=start_date,
            end_date=end_date,
            total_jobs=total_jobs,
            successful_jobs=successful_jobs,
            failed_jobs=failed_jobs,
            cancelled_jobs=cancelled_jobs,
            total_pages=total_pages,
            color_pages=color_pages,
            bw_pages=bw_pages,
            color_jobs=color_jobs,
            bw_jobs=bw_jobs,
            avg_pages_per_job=avg_pages,
            success_rate=success_rate,
            utilization_percentage=100.0,
            total_amount=round(total_amount, 2),
        )

        return PrinterSpecificReportResponse(
            printer=summary_item,
            summary=summary_item,
            user_stats=user_stats,
            recent_jobs=recent_jobs,
        )

    @staticmethod
    def resolve_period_dates(
        period_preset: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        now = datetime.now(timezone.utc)
        preset_lower = (period_preset or "").strip().lower()
        parsed_start = None
        parsed_end = None
        period_label = "All Time"

        if preset_lower == "today":
            parsed_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            parsed_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            period_label = f"Today ({now.strftime('%b %d, %Y')})"
        elif preset_lower == "yesterday":
            y = now - timedelta(days=1)
            parsed_start = y.replace(hour=0, minute=0, second=0, microsecond=0)
            parsed_end = y.replace(hour=23, minute=59, second=59, microsecond=999999)
            period_label = f"Yesterday ({y.strftime('%b %d, %Y')})"
        elif preset_lower == "this_week":
            parsed_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            parsed_end = now
            period_label = f"This Week ({parsed_start.strftime('%b %d')} to {now.strftime('%b %d, %Y')})"
        elif preset_lower == "this_month":
            parsed_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            parsed_end = now
            period_label = f"This Month ({now.strftime('%B %Y')})"
        elif preset_lower == "last_month":
            first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            parsed_end = first_of_this_month - timedelta(microseconds=1)
            parsed_start = parsed_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            period_label = f"Last Month ({parsed_start.strftime('%B %Y')})"
        elif preset_lower == "this_year":
            parsed_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            parsed_end = now
            period_label = f"This Year ({now.strftime('%Y')})"
        elif start_date or end_date:
            if start_date:
                try:
                    parsed_start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                    if parsed_start.tzinfo is not None:
                        parsed_start = parsed_start.astimezone(timezone.utc).replace(tzinfo=None)
                except ValueError:
                    raise AppException(422, "INVALID_REPORT_DATE", "Use an ISO date or timestamp.")
            if end_date:
                try:
                    parsed_end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    if parsed_end.tzinfo is not None:
                        parsed_end = parsed_end.astimezone(timezone.utc).replace(tzinfo=None)
                except ValueError:
                    raise AppException(422, "INVALID_REPORT_DATE", "Use an ISO date or timestamp.")
            if parsed_start and parsed_end:
                period_label = f"{parsed_start.strftime('%b %d, %Y')} to {parsed_end.strftime('%b %d, %Y')}"
            elif parsed_start:
                period_label = f"From {parsed_start.strftime('%b %d, %Y')}"
            elif parsed_end:
                period_label = f"Until {parsed_end.strftime('%b %d, %Y')}"

        return parsed_start, parsed_end, period_label

    @staticmethod
    def generate_analytics_report(
        db: Session,
        department_id: Optional[int] = None,
        printer_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        job_status: Optional[str] = None,
        is_color: Optional[bool] = None,
        period_preset: Optional[str] = None,
    ) -> CollegeAnalyticsReportResponse:
        parsed_start, parsed_end, period_label = ReportService.resolve_period_dates(
            period_preset=period_preset,
            start_date=start_date,
            end_date=end_date,
        )

        # Department / Scope Resolution
        dept = None
        dept_name = "All Departments"
        dept_code = "ALL"
        report_title = "Overall Institutional Printing Audit"
        scope = "All Departments & Campus Printer Stations"

        if department_id is not None:
            dept = db.query(Department).filter(Department.id == department_id).first()
            if not dept:
                raise AppException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_code="DEPARTMENT_NOT_FOUND",
                    message=f"Department with ID {department_id} not found."
                )
            dept_name = dept.name
            dept_code = dept.code
            report_title = f"{dept.name} Printing Performance Report"
            scope = f"Department: {dept.name} ({dept.code})"
        elif printer_id:
            filtered_p = db.query(Printer).filter(Printer.id == printer_id).first()
            if filtered_p:
                dept_name = f"Station: {filtered_p.display_name}"
                dept_code = filtered_p.cups_printer_name
                report_title = f"Printer Station Report: {filtered_p.display_name}"
                scope = f"Station: {filtered_p.display_name} ({filtered_p.cups_printer_name})"

        # Query active printers & departments for inventory metrics
        all_departments = db.query(Department).all()
        all_printers = db.query(Printer).all()
        active_printers_count = len([p for p in all_printers if (p.is_active or p.printer_status == "ONLINE")])
        active_departments_count = len(all_departments)

        # Base Query
        query = (
            db.query(PrintJob, Order, Document, User, Printer)
            .join(Order, Order.id == PrintJob.order_id)
            .outerjoin(Document, Document.id == Order.document_id)
            .outerjoin(User, User.id == Order.user_id)
            .outerjoin(Printer, Printer.id == PrintJob.printer_id)
        )

        if dept:
            query = query.filter(
                or_(
                    User.department_id == dept.id,
                    Order.department == dept.name,
                    Order.department == dept.code,
                )
            )

        if printer_id:
            query = query.filter(PrintJob.printer_id == printer_id)

        if parsed_start:
            query = query.filter(PrintJob.created_at >= parsed_start)

        if parsed_end:
            query = query.filter(PrintJob.created_at <= parsed_end)

        if job_status and job_status.strip():
            st_clean = job_status.strip().upper()
            query = query.filter(PrintJob.status == st_clean)

        records = query.order_by(PrintJob.created_at.desc()).all()

        # Primary Aggregations
        total_jobs = 0
        total_pages = 0
        successful_jobs = 0
        failed_jobs = 0
        cancelled_jobs = 0
        color_pages = 0
        bw_pages = 0
        color_jobs = 0
        bw_jobs = 0
        total_amount = 0.0

        user_data_map: Dict[int, Dict[str, Any]] = {}
        printer_data_map: Dict[str, Dict[str, Any]] = {}
        dept_data_map: Dict[str, Dict[str, Any]] = {}
        monthly_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"jobs": 0, "pages": 0, "revenue": 0.0, "color_pages": 0, "bw_pages": 0})
        daily_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"jobs": 0, "pages": 0, "revenue": 0.0, "color_pages": 0, "bw_pages": 0})
        weekly_day_map: Dict[str, Dict[str, Any]] = {
            "Monday": {"jobs": 0, "pages": 0, "revenue": 0.0, "color_pages": 0, "bw_pages": 0},
            "Tuesday": {"jobs": 0, "pages": 0, "revenue": 0.0, "color_pages": 0, "bw_pages": 0},
            "Wednesday": {"jobs": 0, "pages": 0, "revenue": 0.0, "color_pages": 0, "bw_pages": 0},
            "Thursday": {"jobs": 0, "pages": 0, "revenue": 0.0, "color_pages": 0, "bw_pages": 0},
            "Friday": {"jobs": 0, "pages": 0, "revenue": 0.0, "color_pages": 0, "bw_pages": 0},
            "Saturday": {"jobs": 0, "pages": 0, "revenue": 0.0, "color_pages": 0, "bw_pages": 0},
            "Sunday": {"jobs": 0, "pages": 0, "revenue": 0.0, "color_pages": 0, "bw_pages": 0},
        }

        # Initialize department map
        for d in all_departments:
            dept_data_map[d.code] = {
                "department_id": d.id,
                "department_name": d.name,
                "department_code": d.code,
                "jobs": 0,
                "pages": 0,
                "revenue": 0.0,
                "color_pages": 0,
                "bw_pages": 0,
                "color_jobs": 0,
                "bw_jobs": 0,
                "active_user_ids": set(),
                "printers_count": db.query(Printer).filter(Printer.department_id == d.id).count(),
            }

        # Demographics tracking
        student_users = set()
        faculty_users = set()
        guest_order_count = 0

        for job, order, doc, user, printer in records:
            job_is_color = False
            if order and order.print_settings:
                c_val = order.print_settings.get("colour", order.print_settings.get("color", False))
                if isinstance(c_val, str):
                    job_is_color = c_val.lower() in ["true", "color", "colour", "1"]
                else:
                    job_is_color = bool(c_val)

            if is_color is not None and job_is_color != is_color:
                continue

            total_jobs += 1

            st_val = job.status.value if hasattr(job.status, "value") else str(job.status)
            is_success = st_val == PrintJobStatus.COMPLETED.value
            is_failed = st_val in [PrintJobStatus.FAILED.value, PrintJobStatus.FINAL_FAILED.value]
            is_cancelled = st_val == PrintJobStatus.CANCELLED.value

            if is_success:
                successful_jobs += 1
            elif is_failed:
                failed_jobs += 1
            elif is_cancelled:
                cancelled_jobs += 1

            copies = order.copies if (order and order.copies) else 1
            pages_per_copy = (order.total_pages if order and order.total_pages else (doc.page_count if doc and doc.page_count else 1))
            job_pages = pages_per_copy * copies
            total_pages += job_pages

            job_amount = float(order.amount) if order and order.amount else 0.0
            total_amount += job_amount

            if job_is_color:
                color_jobs += 1
                color_pages += job_pages
            else:
                bw_jobs += 1
                bw_pages += job_pages

            # User Tracking & Demographics
            if user:
                u_key = user.id
                is_student = bool(user.roll_number and user.roll_number.strip())
                if is_student:
                    student_users.add(u_key)
                else:
                    faculty_users.add(u_key)
            else:
                u_key = 0
                guest_order_count += 1

            if u_key not in user_data_map:
                user_data_map[u_key] = {
                    "user_id": user.id if user else None,
                    "user_name": (user.full_name or user.email) if user else "Walk-in Guest",
                    "email": user.email if user else None,
                    "roll_number": user.roll_number if user else None,
                    "role": "STUDENT" if (user and user.roll_number) else ("FACULTY" if user else "GUEST"),
                    "total_jobs": 0,
                    "successful_jobs": 0,
                    "total_pages": 0,
                    "color_pages": 0,
                    "bw_pages": 0,
                }
            user_data_map[u_key]["total_jobs"] += 1
            user_data_map[u_key]["total_pages"] += job_pages
            if is_success:
                user_data_map[u_key]["successful_jobs"] += 1
            if job_is_color:
                user_data_map[u_key]["color_pages"] += job_pages
            else:
                user_data_map[u_key]["bw_pages"] += job_pages

            # Department breakdown
            d_code = None
            if user and user.department_id:
                for d in all_departments:
                    if d.id == user.department_id:
                        d_code = d.code
                        break
            elif order and order.department:
                for d in all_departments:
                    if order.department in (d.name, d.code):
                        d_code = d.code
                        break

            if not d_code:
                d_code = "GENERAL"
                if "GENERAL" not in dept_data_map:
                    dept_data_map["GENERAL"] = {
                        "department_id": None,
                        "department_name": "General Campus Printing",
                        "department_code": "GENERAL",
                        "jobs": 0,
                        "pages": 0,
                        "revenue": 0.0,
                        "color_pages": 0,
                        "bw_pages": 0,
                        "color_jobs": 0,
                        "bw_jobs": 0,
                        "active_user_ids": set(),
                        "printers_count": 0,
                    }

            dept_data_map[d_code]["jobs"] += 1
            dept_data_map[d_code]["pages"] += job_pages
            dept_data_map[d_code]["revenue"] += job_amount
            if user:
                dept_data_map[d_code]["active_user_ids"].add(user.id)
            if job_is_color:
                dept_data_map[d_code]["color_pages"] += job_pages
                dept_data_map[d_code]["color_jobs"] += 1
            else:
                dept_data_map[d_code]["bw_pages"] += job_pages
                dept_data_map[d_code]["bw_jobs"] += 1

            # Printer Tracking
            p_id = printer.id if printer else (
                order.print_settings.get("printer_id", "unassigned") if order and order.print_settings else "unassigned"
            )
            p_name = printer.display_name if printer else "Station Printer"
            cups_name = printer.cups_printer_name if printer else "default_cups"

            if p_id not in printer_data_map:
                printer_data_map[p_id] = {
                    "printer_id": p_id,
                    "printer_name": p_name,
                    "cups_printer_name": cups_name,
                    "total_jobs": 0,
                    "successful_jobs": 0,
                    "failed_jobs": 0,
                    "cancelled_jobs": 0,
                    "total_pages": 0,
                    "color_pages": 0,
                    "bw_pages": 0,
                    "total_amount": 0.0,
                    "status": printer.printer_status if (printer and printer.printer_status) else "ONLINE",
                    "is_active": printer.is_active if (printer and printer.is_active is not None) else True,
                    "location": printer.location if printer else None,
                }
            printer_data_map[p_id]["total_jobs"] += 1
            printer_data_map[p_id]["total_pages"] += job_pages
            printer_data_map[p_id]["total_amount"] += job_amount
            if is_success:
                printer_data_map[p_id]["successful_jobs"] += 1
            elif is_failed:
                printer_data_map[p_id]["failed_jobs"] += 1
            elif is_cancelled:
                printer_data_map[p_id]["cancelled_jobs"] += 1

            if job_is_color:
                printer_data_map[p_id]["color_pages"] += job_pages
            else:
                printer_data_map[p_id]["bw_pages"] += job_pages

            # Time Trends (Monthly, Daily, Weekly)
            if job.created_at:
                m_key = job.created_at.strftime("%Y-%m")
                d_key = job.created_at.strftime("%Y-%m-%d")
                w_day = job.created_at.strftime("%A")

                monthly_map[m_key]["jobs"] += 1
                monthly_map[m_key]["pages"] += job_pages
                monthly_map[m_key]["revenue"] += job_amount
                if job_is_color:
                    monthly_map[m_key]["color_pages"] += job_pages
                else:
                    monthly_map[m_key]["bw_pages"] += job_pages

                daily_map[d_key]["jobs"] += 1
                daily_map[d_key]["pages"] += job_pages
                daily_map[d_key]["revenue"] += job_amount
                if job_is_color:
                    daily_map[d_key]["color_pages"] += job_pages
                else:
                    daily_map[d_key]["bw_pages"] += job_pages

                if w_day in weekly_day_map:
                    weekly_day_map[w_day]["jobs"] += 1
                    weekly_day_map[w_day]["pages"] += job_pages
                    weekly_day_map[w_day]["revenue"] += job_amount
                    if job_is_color:
                        weekly_day_map[w_day]["color_pages"] += job_pages
                    else:
                        weekly_day_map[w_day]["bw_pages"] += job_pages

        # Build Monthly Trends (last 6-12 months sorted chronologically)
        if not monthly_map:
            # Seed past 6 months with zero entries if no data exists so chart has structure
            now = datetime.now(timezone.utc)
            for i in range(5, -1, -1):
                past_m = (now.replace(day=1) - timedelta(days=i * 30)).strftime("%Y-%m")
                monthly_map[past_m] = {"jobs": 0, "pages": 0, "revenue": 0.0, "color_pages": 0, "bw_pages": 0}

        sorted_months = sorted(monthly_map.keys())
        monthly_trends: List[AnalyticsTrendPoint] = []
        for m in sorted_months[-12:]:
            val = monthly_map[m]
            try:
                m_dt = datetime.strptime(m, "%Y-%m")
                label = m_dt.strftime("%b %Y")
            except Exception:
                label = m
            monthly_trends.append(
                AnalyticsTrendPoint(
                    period_label=label,
                    jobs=val["jobs"],
                    pages=val["pages"],
                    revenue=round(val["revenue"], 2),
                    color_pages=val["color_pages"],
                    bw_pages=val["bw_pages"],
                )
            )

        # Build Daily Trends (sorted chronologically, capped at 31)
        sorted_days = sorted(daily_map.keys())
        daily_trends: List[AnalyticsTrendPoint] = []
        for d in sorted_days[-31:]:
            val = daily_map[d]
            try:
                d_dt = datetime.strptime(d, "%Y-%m-%d")
                label = d_dt.strftime("%b %d")
            except Exception:
                label = d
            daily_trends.append(
                AnalyticsTrendPoint(
                    period_label=label,
                    jobs=val["jobs"],
                    pages=val["pages"],
                    revenue=round(val["revenue"], 2),
                    color_pages=val["color_pages"],
                    bw_pages=val["bw_pages"],
                )
            )

        # Build Weekly Trends
        weekly_trends: List[AnalyticsTrendPoint] = []
        for day_name in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
            w_val = weekly_day_map[day_name]
            weekly_trends.append(
                AnalyticsTrendPoint(
                    period_label=day_name[:3],
                    jobs=w_val["jobs"],
                    pages=w_val["pages"],
                    revenue=round(w_val["revenue"], 2),
                    color_pages=w_val["color_pages"],
                    bw_pages=w_val["bw_pages"],
                )
            )

        # Build Department Performance List
        department_performance: List[DepartmentPerformanceItem] = []
        for d_info in dept_data_map.values():
            w_share = round(d_info["pages"] / total_pages * 100, 1) if total_pages > 0 else 0.0
            r_share = round(d_info["revenue"] / total_amount * 100, 1) if total_amount > 0 else 0.0
            department_performance.append(
                DepartmentPerformanceItem(
                    department_id=d_info["department_id"],
                    department_name=d_info["department_name"],
                    department_code=d_info["department_code"],
                    jobs=d_info["jobs"],
                    pages=d_info["pages"],
                    revenue=round(d_info["revenue"], 2),
                    color_pages=d_info["color_pages"],
                    bw_pages=d_info["bw_pages"],
                    color_jobs=d_info["color_jobs"],
                    bw_jobs=d_info["bw_jobs"],
                    active_users=len(d_info["active_user_ids"]),
                    printers_count=d_info["printers_count"],
                    workload_share_pct=w_share,
                    revenue_share_pct=r_share,
                )
            )
        department_performance.sort(key=lambda x: x.pages, reverse=True)

        # Build Printer Stats List
        printer_stats: List[PrinterUtilizationStat] = []
        for p in printer_data_map.values():
            p_util = round(p["total_pages"] / total_pages * 100, 1) if total_pages > 0 else 0.0
            s_rate = round(p["successful_jobs"] / p["total_jobs"] * 100, 1) if p["total_jobs"] > 0 else 100.0
            printer_stats.append(
                PrinterUtilizationStat(
                    printer_id=p["printer_id"],
                    printer_name=p["printer_name"],
                    cups_printer_name=p["cups_printer_name"],
                    total_jobs=p["total_jobs"],
                    total_pages=p["total_pages"],
                    utilization_percentage=p_util,
                    success_rate=s_rate,
                    successful_jobs=p.get("successful_jobs", 0),
                    failed_jobs=p.get("failed_jobs", 0),
                    cancelled_jobs=p.get("cancelled_jobs", 0),
                    color_pages=p.get("color_pages", 0),
                    bw_pages=p.get("bw_pages", 0),
                    total_amount=round(p.get("total_amount", 0.0), 2),
                    status=p.get("status", "ONLINE"),
                    is_active=p.get("is_active", True),
                    location=p.get("location"),
                )
            )
        printer_stats.sort(key=lambda x: x.total_pages, reverse=True)

        # Build Demographics Summary
        total_active_users = len(user_data_map) - (1 if 0 in user_data_map else 0)
        avg_pages_user = round(total_pages / total_active_users, 1) if total_active_users > 0 else 0.0
        avg_jobs_user = round(total_jobs / total_active_users, 1) if total_active_users > 0 else 0.0
        user_demographics = UserDemographicsSummary(
            total_active_users=total_active_users,
            faculty_count=len(faculty_users),
            student_count=len(student_users),
            guest_count=guest_order_count,
            avg_pages_per_user=avg_pages_user,
            avg_jobs_per_user=avg_jobs_user,
        )

        # Optional User Stats list (for audit drill-down only)
        user_stats: List[UserReportStat] = []
        for u in user_data_map.values():
            s_rate = round(u["successful_jobs"] / u["total_jobs"] * 100, 1) if u["total_jobs"] > 0 else 100.0
            user_stats.append(
                UserReportStat(
                    user_id=u["user_id"],
                    user_name=u["user_name"],
                    email=u["email"],
                    roll_number=u["roll_number"],
                    role=u.get("role", "STUDENT"),
                    total_jobs=u["total_jobs"],
                    total_pages=u["total_pages"],
                    color_pages=u["color_pages"],
                    bw_pages=u["bw_pages"],
                    success_rate=s_rate,
                )
            )
        user_stats.sort(key=lambda x: x.total_pages, reverse=True)

        # Calculate Prior Period Delta for Automated Remarks
        prev_pages = 0
        if parsed_start and parsed_end:
            duration = parsed_end - parsed_start
            prev_end = parsed_start
            prev_start = prev_end - duration
            prev_count_query = db.query(PrintJob).filter(PrintJob.created_at >= prev_start, PrintJob.created_at < prev_end)
            if dept:
                prev_count_query = prev_count_query.join(Order, Order.id == PrintJob.order_id).outerjoin(User, User.id == Order.user_id).filter(
                    or_(User.department_id == dept.id, Order.department == dept.name, Order.department == dept.code)
                )
            prev_jobs = prev_count_query.all()
            for pj in prev_jobs:
                p_order = db.query(Order).filter(Order.id == pj.order_id).first()
                if p_order and p_order.total_pages:
                    prev_pages += p_order.total_pages * (p_order.copies or 1)
                else:
                    prev_pages += 1

        if prev_pages > 0 and total_pages > 0:
            diff_pct = round(((total_pages - prev_pages) / prev_pages) * 100, 1)
            if diff_pct > 0:
                volume_obs = f"Printing volume increased by {diff_pct}% compared to the prior period ({total_pages} vs {prev_pages} pages)."
            elif diff_pct < 0:
                volume_obs = f"Printing volume decreased by {abs(diff_pct)}% compared to the prior period ({total_pages} vs {prev_pages} pages)."
            else:
                volume_obs = f"Printing volume remained consistent with the prior period at {total_pages} pages."
        else:
            volume_obs = f"Current period recorded {total_jobs} jobs and {total_pages} printed pages across the network."

        bw_pct = round(bw_pages / total_pages * 100, 1) if total_pages > 0 else 0.0
        color_pct = round(color_pages / total_pages * 100, 1) if total_pages > 0 else 0.0
        color_obs = f"Black and white documents accounted for {bw_pct}% of total pages ({bw_pages} pages), maintaining economical consumable costs. Color pages represented {color_pct}%."

        decided_jobs = successful_jobs + failed_jobs
        success_rate = round(successful_jobs / decided_jobs * 100, 1) if decided_jobs > 0 else (100.0 if total_jobs > 0 else 0.0)
        rev_obs = f"Total recorded order value of Rs {total_amount:.2f} with a {success_rate}% job success rate across {total_jobs} submissions."

        top_dept_obs = "Printing operations distributed evenly across all academic departments."
        if department_performance:
            lead_d = department_performance[0]
            if lead_d.pages > 0:
                top_dept_obs = f"{lead_d.department_name} accounted for the highest printing consumption ({lead_d.workload_share_pct}% of total institutional volume, {lead_d.pages} pages)."

        fleet_obs = "All campus print stations maintained active status."
        if printer_stats:
            lead_p = printer_stats[0]
            fleet_obs = f"Station '{lead_p.printer_name}' handled the heaviest workload ({lead_p.utilization_percentage}% share) with {lead_p.success_rate}% hardware reliability."

        recommendations = [
            "Maintain paper replenishment schedules prior to peak weekday hours (Tuesdays and Wednesdays).",
            "Encourage duplex (two-sided) printing for assignments to reduce institutional paper consumption by up to 30%.",
            "Ensure regular firmware and toner checks on high-demand departmental kiosks before semester examination cycles.",
        ]

        remarks = AutomatedRemarks(
            volume_observation=volume_obs,
            color_ratio_observation=color_obs,
            revenue_observation=rev_obs,
            fleet_observation=fleet_obs,
            department_observation=top_dept_obs,
            key_recommendations=recommendations,
        )

        avg_pages = round(total_pages / total_jobs, 2) if total_jobs > 0 else 0.0
        summary = DepartmentSummaryReport(
            department_id=dept.id if dept else None,
            department_name=dept_name,
            department_code=dept_code,
            start_date=start_date,
            end_date=end_date,
            total_jobs=total_jobs,
            total_pages=total_pages,
            successful_jobs=successful_jobs,
            failed_jobs=failed_jobs,
            cancelled_jobs=cancelled_jobs,
            color_pages=color_pages,
            bw_pages=bw_pages,
            color_jobs=color_jobs,
            bw_jobs=bw_jobs,
            avg_pages_per_job=avg_pages,
            total_amount=round(total_amount, 2),
        )

        return CollegeAnalyticsReportResponse(
            report_title=report_title,
            scope=scope,
            period_label=period_label,
            start_date=start_date,
            end_date=end_date,
            summary=summary,
            monthly_trends=monthly_trends,
            daily_trends=daily_trends,
            weekly_trends=weekly_trends,
            department_performance=department_performance,
            printer_stats=printer_stats,
            user_demographics=user_demographics,
            remarks=remarks,
            active_printers_count=active_printers_count,
            active_departments_count=active_departments_count,
            user_stats=user_stats,
        )

report_service = ReportService()


