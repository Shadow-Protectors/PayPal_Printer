from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.api.dependencies import get_current_admin
from app.schemas.department import (
    DepartmentListItem,
    DepartmentDetailResponse,
    PublicDepartmentItem,
    DepartmentCreate,
    DepartmentUpdate,
)
from app.services.department_service import department_service
from fastapi import status

router = APIRouter(prefix="/api/departments", tags=["Department Management"])

@router.get("/public", response_model=List[PublicDepartmentItem])
def list_public_departments(
    db: Session = Depends(get_db),
):
    """
    Returns active departments from DB for public selection (e.g. student signup & profile selection).
    No authentication required.
    """
    return department_service.get_public_departments(db)

@router.get("", response_model=List[DepartmentListItem])
def list_departments(
    q: Optional[str] = Query(None, description="Search term for department name or code"),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Returns all departments with real-time aggregate counts (users, printers, jobs, pages).
    Supports keyword search by department name or code.
    Accessible only to authenticated administrators.
    """
    return department_service.get_departments(db, search=q)

@router.post("", response_model=DepartmentListItem, status_code=status.HTTP_201_CREATED)
def create_department(
    data: DepartmentCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Creates a new department record in the database.
    Accessible only to authenticated administrators.
    """
    return department_service.create_department(db, data)

@router.put("/{department_id}", response_model=DepartmentListItem)
def update_department(
    department_id: int,
    data: DepartmentUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Updates an existing department record.
    Accessible only to authenticated administrators.
    """
    return department_service.update_department(db, department_id, data)

@router.delete("/{department_id}")
def delete_department(
    department_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Deletes an existing department if no printers are assigned.
    Accessible only to authenticated administrators.
    """
    return department_service.delete_department(db, department_id)

@router.get("/{department_id}", response_model=DepartmentDetailResponse)
def get_department_detail(
    department_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Returns detailed information about a specific department:
    metadata, summary KPIs, associated users, assigned printers, and recent print jobs.
    Accessible only to authenticated administrators.
    """
    return department_service.get_department_detail(db, department_id=department_id)

@router.get("/{department_id}/report")
def get_department_report_nested(
    department_id: int,
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
    Nested endpoint for department report.
    """
    from app.services.report_service import report_service
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
