from app.services.printer_availability import printer_state
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.db.models.print_server import PrintServer, PrintServerStatus
from app.db.models.printer import Printer
from app.schemas.print_server import PrintServerResponse, PrinterResponse
from app.utils.errors import AppException

router = APIRouter(prefix="/api/print-servers", tags=["Print Servers"])

def _update_server_offline_status(server: PrintServer, db: Session):
    """
    Offline Detection (Section 42):
    In production, checks last_heartbeat.
    In development/demo mode, maintains ONLINE status for enabled stations.
    """
    if settings.ENVIRONMENT.lower() in ("production", "prod"):
        if server.status not in [PrintServerStatus.DISABLED, PrintServerStatus.MAINTENANCE]:
            timeout = timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS)
            now = datetime.now(timezone.utc)
            if server.last_heartbeat:
                hb = server.last_heartbeat
                if hb.tzinfo is None:
                    hb = hb.replace(tzinfo=timezone.utc)
                if hb < now - timeout:
                    if server.status != PrintServerStatus.OFFLINE:
                        server.status = PrintServerStatus.OFFLINE
                        db.commit()
            else:
                if server.status != PrintServerStatus.OFFLINE:
                    server.status = PrintServerStatus.OFFLINE
                    db.commit()
    else:
        if server.is_enabled and server.status not in [PrintServerStatus.DISABLED, PrintServerStatus.MAINTENANCE]:
            if server.status != PrintServerStatus.ONLINE:
                server.status = PrintServerStatus.ONLINE
                db.commit()

@router.get("", response_model=List[PrintServerResponse])
def list_print_servers(
    department_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(PrintServer)
    if department_id is not None:
        query = query.filter(PrintServer.department_id == department_id)
    servers = query.all()
    results = []
    for s in servers:
        _update_server_offline_status(s, db)
        printers = db.query(Printer).filter(
            Printer.server_id == s.id,
            Printer.is_enabled == True
        ).all()
        results.append(PrintServerResponse(
            id=s.id,
            name=s.name,
            location=s.location,
            department_id=s.department_id,
            status=s.status,
            last_heartbeat=s.last_heartbeat,
            printer_state=s.printer_state,
            paper_state=s.paper_state,
            printers=[PrinterResponse.model_validate(p).model_copy(update={"printer_status": printer_state(p, db.get(PrintServer, p.server_id))}) for p in printers]
        ))
    return results

@router.get("/printers", response_model=List[PrinterResponse])
def list_all_printers(
    department_id: Optional[int] = None,
    server_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Printer).filter(Printer.is_enabled == True)
    if department_id is not None:
        # Either directly assigned to department or assigned to a station in that department
        matching_servers = db.query(PrintServer.id).filter(PrintServer.department_id == department_id).subquery()
        query = query.filter(
            (Printer.department_id == department_id) | (Printer.server_id.in_(matching_servers))
        )
    if server_id is not None:
        query = query.filter(Printer.server_id == server_id)
    printers = query.all()
    return [PrinterResponse.model_validate(p).model_copy(update={"printer_status": printer_state(p, db.get(PrintServer, p.server_id))}) for p in printers]

@router.get("/{server_id}", response_model=PrintServerResponse)
def get_print_server(server_id: str, db: Session = Depends(get_db)):
    s = db.query(PrintServer).filter(PrintServer.id == server_id).first()
    if not s:
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="NOT_FOUND",
            message="Print server station not found."
        )

    _update_server_offline_status(s, db)
    printers = db.query(Printer).filter(Printer.server_id == s.id, Printer.is_enabled == True).all()
    return PrintServerResponse(
        id=s.id,
        name=s.name,
        location=s.location,
        department_id=s.department_id,
        status=s.status,
        last_heartbeat=s.last_heartbeat,
        printer_state=s.printer_state,
        paper_state=s.paper_state,
        printers=[PrinterResponse.model_validate(p).model_copy(update={"printer_status": printer_state(p, db.get(PrintServer, p.server_id))}) for p in printers]
    )
