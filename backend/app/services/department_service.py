from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.db.models.department import Department
from app.db.models.user import User
from app.db.models.printer import Printer
from app.db.models.order import Order
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.document import Document
from app.schemas.department import (
    DepartmentListItem,
    DepartmentDetailResponse,
    DepartmentUser,
    DepartmentPrinter,
    PublicDepartmentItem,
    DepartmentCreate,
    DepartmentUpdate,
)
from app.schemas.admin import RecentPrintJob
from app.services.audit_service import audit_service
from app.utils.errors import AppException
from fastapi import status

class DepartmentService:
    @staticmethod
    def get_departments(
        db: Session,
        search: Optional[str] = None
    ) -> List[DepartmentListItem]:
        query = db.query(Department)
        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Department.name.ilike(term),
                    Department.code.ilike(term),
                    Department.description.ilike(term),
                )
            )

        departments = query.order_by(Department.name.asc()).all()
        result: List[DepartmentListItem] = []

        for dept in departments:
            # Users count
            users_count = db.query(User).filter(
                or_(
                    User.department_id == dept.id,
                    User.department == dept.name,
                    User.department == dept.code,
                )
            ).count()

            # Printers count
            printers_count = db.query(Printer).filter(
                Printer.department_id == dept.id
            ).count()

            # Jobs & pages count through order / user
            orders = (
                db.query(Order)
                .join(User, User.id == Order.user_id, isouter=True)
                .filter(
                    or_(
                        User.department_id == dept.id,
                        Order.department == dept.name,
                        Order.department == dept.code,
                    )
                )
                .all()
            )

            jobs_count = len(orders)
            pages_count = sum((o.total_pages or 1) * (o.copies or 1) for o in orders)

            result.append(
                DepartmentListItem(
                    id=dept.id,
                    code=dept.code,
                    name=dept.name,
                    description=dept.description,
                    users_count=users_count,
                    printers_count=printers_count,
                    jobs_count=jobs_count,
                    pages_count=pages_count,
                    created_at=dept.created_at.strftime("%Y-%m-%d %H:%M:%S") if dept.created_at else "",
                )
            )

        return result

    @staticmethod
    def get_department_detail(db: Session, department_id: int) -> DepartmentDetailResponse:
        dept = db.query(Department).filter(Department.id == department_id).first()
        if not dept:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="DEPARTMENT_NOT_FOUND",
                message=f"Department with ID {department_id} not found."
            )

        # Associated users
        users = (
            db.query(User)
            .filter(
                or_(
                    User.department_id == dept.id,
                    User.department == dept.name,
                    User.department == dept.code,
                )
            )
            .order_by(User.full_name.asc())
            .all()
        )
        user_items = [
            DepartmentUser(
                id=u.id,
                full_name=u.full_name,
                email=u.email,
                phone=getattr(u, "phone", None),
                roll_number=u.roll_number,
                role=u.role.value if hasattr(u.role, "value") else str(u.role),
                is_active=u.is_active,
                created_at=u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else "",
            )
            for u in users
        ]

        # Associated printers
        printers = (
            db.query(Printer)
            .filter(Printer.department_id == dept.id)
            .order_by(Printer.display_name.asc())
            .all()
        )
        printer_items = [
            DepartmentPrinter(
                id=p.id,
                cups_printer_name=p.cups_printer_name,
                display_name=p.display_name,
                supports_color=p.supports_color,
                supports_duplex=p.supports_duplex,
                is_active=p.is_active,
                created_at=p.created_at.strftime("%Y-%m-%d %H:%M:%S") if p.created_at else "",
            )
            for p in printers
        ]

        # Department orders and print jobs
        query_jobs = (
            db.query(PrintJob, Order, Document, User, Printer)
            .join(Order, Order.id == PrintJob.order_id)
            .outerjoin(Document, Document.id == Order.document_id)
            .outerjoin(User, User.id == Order.user_id)
            .outerjoin(Printer, Printer.id == PrintJob.printer_id)
            .filter(
                or_(
                    User.department_id == dept.id,
                    Order.department == dept.name,
                    Order.department == dept.code,
                )
            )
            .order_by(PrintJob.created_at.desc())
            .all()
        )

        jobs_count = len(query_jobs)
        pages_count = 0
        color_pages = 0
        bw_pages = 0
        recent_jobs: List[RecentPrintJob] = []

        for idx, (job, order, doc, user, p) in enumerate(query_jobs):
            status_val = job.status.value if hasattr(job.status, "value") else str(job.status)
            copies = order.copies if (order and order.copies) else 1
            pages_per_copy = (order.total_pages if order and order.total_pages else (doc.page_count if doc and doc.page_count else 1))
            total_job_pages = pages_per_copy * copies

            is_color = False
            if order and order.print_settings:
                c_val = order.print_settings.get("colour", order.print_settings.get("color", False))
                if isinstance(c_val, str):
                    is_color = c_val.lower() in ["true", "color", "colour", "1"]
                else:
                    is_color = bool(c_val)

            if status_val == PrintJobStatus.COMPLETED.value:
                pages_count += total_job_pages
                if is_color:
                    color_pages += total_job_pages
                else:
                    bw_pages += total_job_pages

            if idx < 50:
                printer_name = p.display_name if p else (
                    order.print_settings.get("printer_name", "Station Printer") if order and order.print_settings else "Station Printer"
                )
                finish_dt = job.completed_at or (job.updated_at if status_val in [
                    PrintJobStatus.COMPLETED.value,
                    PrintJobStatus.CANCELLED.value,
                    PrintJobStatus.FAILED.value,
                    PrintJobStatus.FINAL_FAILED.value
                ] else None)
                recent_jobs.append(
                    RecentPrintJob(
                        id=job.id,
                        order_id=order.id if order else "",
                        document_name=doc.original_filename if doc else "Document",
                        user_name=(user.full_name or user.email) if user else "Guest",
                        user_email=user.email if user else None,
                        department_id=dept.id,
                        department_name=dept.name,
                        printer_name=printer_name,
                        pages=total_job_pages,
                        copies=copies,
                        is_color=is_color,
                        status=status_val,
                        created_at=job.created_at.strftime("%Y-%m-%d %H:%M:%S") if job.created_at else "",
                        completed_at=finish_dt.strftime("%Y-%m-%d %H:%M:%S") if finish_dt else None,
                        error_message=job.error_message,
                    )
                )

        return DepartmentDetailResponse(
            id=dept.id,
            code=dept.code,
            name=dept.name,
            description=dept.description,
            users_count=len(users),
            printers_count=len(printers),
            jobs_count=jobs_count,
            pages_count=pages_count,
            color_pages=color_pages,
            bw_pages=bw_pages,
            created_at=dept.created_at.strftime("%Y-%m-%d %H:%M:%S") if dept.created_at else "",
            users=user_items,
            printers=printer_items,
            recent_jobs=recent_jobs,
        )

    @staticmethod
    def get_public_departments(db: Session) -> List[PublicDepartmentItem]:
        depts = db.query(Department).order_by(Department.name.asc()).all()
        return [
            PublicDepartmentItem(
                id=d.id,
                code=d.code,
                name=d.name,
                description=d.description
            )
            for d in depts
        ]

    @staticmethod
    def create_department(db: Session, data: DepartmentCreate) -> DepartmentListItem:
        clean_code = data.code.strip().upper()
        clean_name = data.name.strip()
        if not clean_code or not clean_name:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_DEPARTMENT_DATA",
                message="Department code and name are required."
            )
        if db.query(Department).filter(Department.code == clean_code).first():
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="DEPARTMENT_CODE_EXISTS",
                message=f"Department code '{clean_code}' already exists."
            )
        if db.query(Department).filter(Department.name == clean_name).first():
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="DEPARTMENT_NAME_EXISTS",
                message=f"Department name '{clean_name}' already exists."
            )
        dept = Department(
            code=clean_code,
            name=clean_name,
            description=data.description.strip() if data.description else None
        )
        db.add(dept)
        db.commit()
        db.refresh(dept)
        audit_service.log(
            db,
            action="DEPARTMENT_CREATED",
            entity_type="Department",
            entity_id=str(dept.id),
            meta_data={"code": dept.code, "name": dept.name},
            commit=True,
        )
        return DepartmentListItem(
            id=dept.id,
            code=dept.code,
            name=dept.name,
            description=dept.description,
            users_count=0,
            printers_count=0,
            jobs_count=0,
            pages_count=0,
            created_at=dept.created_at.strftime("%Y-%m-%d %H:%M:%S") if dept.created_at else "",
        )

    @staticmethod
    def update_department(db: Session, department_id: int, data: DepartmentUpdate) -> DepartmentListItem:
        dept = db.query(Department).filter(Department.id == department_id).first()
        if not dept:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="DEPARTMENT_NOT_FOUND",
                message=f"Department with ID {department_id} not found."
            )
        if data.code is not None and data.code.strip():
            clean_code = data.code.strip().upper()
            if clean_code != dept.code:
                existing = db.query(Department).filter(Department.code == clean_code, Department.id != dept.id).first()
                if existing:
                    raise AppException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        error_code="DEPARTMENT_CODE_EXISTS",
                        message=f"Department code '{clean_code}' already exists."
                    )
                dept.code = clean_code
        if data.name is not None and data.name.strip():
            clean_name = data.name.strip()
            if clean_name != dept.name:
                existing = db.query(Department).filter(Department.name == clean_name, Department.id != dept.id).first()
                if existing:
                    raise AppException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        error_code="DEPARTMENT_NAME_EXISTS",
                        message=f"Department name '{clean_name}' already exists."
                    )
                dept.name = clean_name
        if data.description is not None:
            dept.description = data.description.strip() if data.description.strip() else None

        db.commit()
        db.refresh(dept)
        audit_service.log(
            db,
            action="DEPARTMENT_UPDATED",
            entity_type="Department",
            entity_id=str(dept.id),
            meta_data={"code": dept.code, "name": dept.name},
            commit=True,
        )
        return DepartmentService.get_departments(db, search=dept.code)[0]

    @staticmethod
    def delete_department(db: Session, department_id: int) -> dict:
        dept = db.query(Department).filter(Department.id == department_id).first()
        if not dept:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="DEPARTMENT_NOT_FOUND",
                message=f"Department with ID {department_id} not found."
            )
        printers_count = db.query(Printer).filter(Printer.department_id == dept.id).count()
        if printers_count > 0:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="DEPARTMENT_HAS_PRINTERS",
                message=f"Cannot delete department with {printers_count} assigned printer(s). Reassign them first."
            )
        dept_name = dept.name
        db.query(User).filter(User.department_id == dept.id).update({User.department_id: None})
        db.delete(dept)
        db.commit()
        audit_service.log(
            db,
            action="DEPARTMENT_DELETED",
            entity_type="Department",
            entity_id=str(department_id),
            meta_data={"name": dept_name},
            commit=True,
        )
        return {"success": True, "message": f"Department '{dept_name}' deleted successfully."}

department_service = DepartmentService()
