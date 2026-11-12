from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status, UploadFile, File, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.api.dependencies import get_current_admin
from app.schemas.admin import (
    AdminDashboardResponse,
    AdminPrinterItem,
    AdminPrinterCreate,
    AdminPrinterUpdate,
    PrinterTestConnectionResponse,
    AdminDiscoveredPrinterItem,
    AdminPrintAgentItem,
    AdminPrintAgentCreate,
    AdminPrintServerUpdate,
    AdminAgentCupsPrinterItem,
    AdminUserItem,
    AdminUserCreate,
    AdminUserUpdate,
    PaginatedAdminUsersResponse,
    AdminSystemSettings,
    AdminSystemSettingsUpdate,
    AdminDatabaseStatusResponse,
    UserImportSummary,
    AuditLogItem,
)
from app.schemas.report import PrinterSpecificReportResponse
from app.services.admin_service import admin_service

router = APIRouter(prefix="/api/admin", tags=["Admin Portal"])

@router.get("/dashboard", response_model=AdminDashboardResponse)
def get_admin_dashboard(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Returns aggregated metrics for the enterprise admin dashboard.
    Only accessible by authenticated administrators.
    """
    return admin_service.get_dashboard_metrics(db)

# ----------------- PRINTER MANAGEMENT -----------------

@router.get("/printers", response_model=List[AdminPrinterItem])
def get_admin_printers(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Returns all registered printer hardware stations with real-time status and diagnostics.
    """
    return admin_service.get_printers(db)

@router.post("/printers", response_model=AdminPrinterItem, status_code=status.HTTP_201_CREATED)
def create_admin_printer(
    data: AdminPrinterCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Manually registers a new printer assigned to a Print Agent.
    """
    return admin_service.create_printer(data, db)

@router.post("/printers/{printer_id}/test-connection", response_model=PrinterTestConnectionResponse)
def test_admin_printer_connection(
    printer_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Instructs the assigned Print Agent to verify printer existence in CUPS and network reachability.
    Only after successful validation is the printer activated.
    """
    return admin_service.test_printer_connection(printer_id, db)

@router.patch("/printers/{printer_id}", response_model=AdminPrinterItem)
def update_admin_printer(
    printer_id: str,
    data: AdminPrinterUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Updates printer display details, department assignment, or active toggle.
    """
    return admin_service.update_printer(printer_id, data, db)

@router.delete("/printers/{printer_id}")
def delete_admin_printer(
    printer_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Deletes a registered printer if there are no active jobs in progress.
    """
    admin_service.delete_printer(printer_id, db)
    return {"message": f"Printer '{printer_id}' deleted successfully"}

@router.get("/printers/{printer_id}/report", response_model=PrinterSpecificReportResponse)
def get_admin_printer_report(
    printer_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    is_color: Optional[bool] = Query(None),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Returns printer-specific performance, workload and user breakdown report.
    """
    from app.services.report_service import report_service
    return report_service.generate_printer_specific_report(
        db=db,
        printer_id=printer_id,
        start_date=start_date,
        end_date=end_date,
        job_status=status,
        is_color=is_color,
    )

# ----------------- PRINT AGENTS & DISCOVERY -----------------

@router.get("/print-agents", response_model=List[AdminPrintAgentItem])
def get_admin_print_agents(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Lists all registered Print Agents with connection health and hardware attributes.
    """
    return admin_service.get_print_servers(db)

@router.post("/print-agents", response_model=AdminPrintAgentItem, status_code=status.HTTP_201_CREATED)
def create_admin_print_agent(
    data: AdminPrintAgentCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Registers a new Raspberry Pi Print Agent station.
    """
    return admin_service.create_print_server(data, db)

@router.patch("/print-agents/{server_id}")
@router.patch("/print-servers/{server_id}")
def update_admin_print_server(
    server_id: str,
    data: AdminPrintServerUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Updates print server state (ONLINE, OFFLINE, MAINTENANCE, DISABLED) or physical location.
    """
    admin_service.update_print_server(server_id, data, db)
    return {"message": "Print server updated successfully"}

@router.delete("/print-agents/{server_id}")
def delete_admin_print_agent(
    server_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Deletes a registered Print Agent and unmaps/cleans assigned printers.
    """
    admin_service.delete_print_server(server_id, db)
    return {"message": f"Print Agent '{server_id}' deleted successfully"}

@router.get("/print-agents/{server_id}/cups-printers", response_model=List[AdminAgentCupsPrinterItem])
def get_admin_agent_cups_printers(
    server_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Queries the assigned Print Agent on the Raspberry Pi to retrieve
    all physical CUPS printers detected on that machine.
    """
    return admin_service.get_agent_cups_printers(server_id, db)

@router.get("/discovered-printers", response_model=List[AdminDiscoveredPrinterItem])
def get_admin_discovered_printers(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Lists unregistered printers reported by Print Agent heartbeats.
    """
    return admin_service.get_discovered_printers(db)

@router.delete("/discovered-printers/{discovered_id}")
def dismiss_admin_discovered_printer(
    discovered_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Dismisses a discovered printer record from the inbox.
    """
    admin_service.dismiss_discovered_printer(discovered_id, db)
    return {"message": "Discovered printer dismissed"}


# ----------------- USER MANAGEMENT -----------------

@router.get("/users", response_model=PaginatedAdminUsersResponse)
def get_admin_users(
    page: int = Query(1, ge=1),
    limit: int = Query(15, ge=1, le=100),
    search: Optional[str] = Query(None),
    department_id: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Search and paginate user directory with department links and printing metrics.
    """
    return admin_service.get_users(
        db=db,
        page=page,
        limit=limit,
        search=search,
        department_id=department_id,
        role=role,
        is_active=is_active
    )

@router.post("/users", response_model=AdminUserItem, status_code=status.HTTP_201_CREATED)
def create_admin_user(
    data: AdminUserCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Creates a new user account with specified department and role.
    """
    return admin_service.create_user(data, db)

@router.patch("/users/{user_id}", response_model=AdminUserItem)
def update_admin_user(
    user_id: int,
    data: AdminUserUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Updates user details: department assignment, role, or active status toggle.
    """
    return admin_service.update_user(user_id, data, db)

@router.delete("/users/{user_id}", status_code=status.HTTP_200_OK)
def delete_admin_user(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Deletes a user account from the system directory.
    """
    admin_service.delete_user(user_id, admin.id, db)
    return {"message": "User deleted successfully."}


# ----------------- SYSTEM SETTINGS -----------------

@router.get("/settings", response_model=AdminSystemSettings)
def get_admin_settings(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Returns platform runtime configurations, rates, and operational parameters.
    """
    from app.services.settings_service import load_platform_settings
    load_platform_settings(db)
    return admin_service.get_settings(admin.email)

@router.patch("/settings", response_model=AdminSystemSettings)
def update_admin_settings(
    data: AdminSystemSettingsUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Updates platform operational parameters (pricing rates, quotas, timeouts).
    """
    from app.services.settings_service import save_platform_settings
    result = admin_service.update_settings(data, admin.email)
    save_platform_settings(db, data)
    from app.services.audit_service import audit_service
    audit_service.log(db, action="SETTINGS_UPDATED", user_id=admin.id,
                      entity_type="Settings", entity_id="system",
                      meta_data=data.model_dump(exclude_unset=True), commit=True)
    return result
 
# ----------------- DATABASE & PRODUCTION DATA -----------------

@router.get("/database/status", response_model=AdminDatabaseStatusResponse)
def get_database_status(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Returns live database health, latency, masked URL, and table record counts.
    """
    return admin_service.get_database_status(db)

@router.get("/users/import/template")
def download_roster_template(
    admin: User = Depends(get_current_admin)
):
    """
    Downloads pre-formatted Excel template for importing campus/student rosters.
    """
    template_bytes = admin_service.generate_roster_template()
    return Response(
        content=template_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=student_roster_template.xlsx"}
    )

@router.post("/users/import", response_model=UserImportSummary)
async def import_user_roster(
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Imports real user and department rosters from an uploaded .xlsx or .csv file.
    """
    contents = await file.read()
    return admin_service.import_roster(contents, file.filename or "roster.xlsx", db)


# ----------------- AUDIT LOGS & JOB REMEDIATION -----------------

@router.get("/audit-logs", response_model=List[AuditLogItem])
def get_admin_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Returns security and operational audit trail records with actor identity and payload metadata.
    """
    from app.services.audit_service import audit_service
    logs = audit_service.get_logs(db, limit=limit, offset=offset, action=action, entity_type=entity_type)
    return [
        AuditLogItem(
            id=l.id,
            user_id=l.user_id,
            actor_type=l.actor_type,
            action=l.action,
            entity_type=l.entity_type,
            entity_id=l.entity_id,
            meta_data=l.meta_data,
            created_at=l.created_at.strftime("%Y-%m-%d %H:%M:%S") if l.created_at else "",
        )
        for l in logs
    ]


@router.post("/jobs/{job_id}/retry")
def retry_admin_print_job(
    job_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Manually retries a failed or cancelled print job, issuing a fresh single-use release code
    and re-queuing the job for pickup at the department station.
    """
    return admin_service.retry_print_job(job_id=job_id, admin_user=admin, db=db)


