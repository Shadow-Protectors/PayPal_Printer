from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.config.settings import settings
from app.db.models.print_server import PrintServer, PrintServerStatus
from app.db.models.order import Order, OrderStatus
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.document import Document
from app.schemas.print_server import HeartbeatRequest, HeartbeatResponse
from app.schemas.agent import AgentJobResponse, AgentReleaseRequest, AgentReleaseResponse, AgentJobStatusUpdate
from app.schemas.common import MessageResponse
from app.schemas.order import sanitize_print_settings
from app.services.otp_service import otp_service
from app.services.job_service import job_service
from app.api.dependencies import get_authenticated_agent

from app.db.models.printer import Printer
from app.db.models.discovered_printer import DiscoveredPrinter
from fastapi.responses import FileResponse
from app.services.storage_service import storage_service
from app.utils.errors import AppException

router = APIRouter(prefix="/api/agent", tags=["Agent Operations"])

@router.post("/heartbeat", response_model=HeartbeatResponse)
def agent_heartbeat(
    req: HeartbeatRequest,
    server: PrintServer = Depends(get_authenticated_agent),
    db: Session = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    server.last_heartbeat = now
    server.last_seen = now
    server.printer_state = req.printerState
    server.paper_state = req.paperState
    if req.version:
        server.software_version = req.version.strip()
    if server.status not in (PrintServerStatus.DISABLED, PrintServerStatus.MAINTENANCE):
        server.status = PrintServerStatus.ONLINE

    # Heartbeat printer synchronization & mismatch validation
    if req.printers is not None:
        registered_printers = db.query(Printer).filter(Printer.server_id == server.id).all()
        reported_by_name = {
            r.cups_printer_name.strip().lower(): r for r in req.printers if r.cups_printer_name
        }

        # 1. Check registered printers for mismatches or missing status
        for p in registered_printers:
            p_name_key = p.cups_printer_name.strip().lower()
            if p_name_key not in reported_by_name:
                p.has_mismatch = True
                p.mismatch_details = (
                    f"CUPS printer '{p.cups_printer_name}' not found on Print Agent"
                    if req.printers else "Printer not detected in CUPS (no connected printers reported)"
                )
                p.printer_status = "OFFLINE"
            else:
                rep = reported_by_name[p_name_key]
                # Older admin clients map by queue name only. Bind missing metadata
                # from the authenticated station's own observed inventory.
                if not p.device_uri and rep.device_uri:
                    p.device_uri = rep.device_uri
                if not p.ip_address and rep.ip_address:
                    p.ip_address = rep.ip_address
                # Compare static IP if both registered and reported have IP
                if p.ip_address and rep.ip_address and p.ip_address.strip() != rep.ip_address.strip():
                    p.has_mismatch = True
                    p.mismatch_details = (
                        f"IP Mismatch: Registered ({p.ip_address}) does not match reported ({rep.ip_address})"
                    )
                elif p.device_uri and rep.device_uri and p.device_uri.strip() != rep.device_uri.strip():
                    p.has_mismatch = True
                    p.mismatch_details = (
                        f"Device URI Mismatch: Registered ({p.device_uri}) does not match reported ({rep.device_uri})"
                    )
                else:
                    p.has_mismatch = False
                    p.mismatch_details = None

                p.printer_status = rep.status or "UNKNOWN"
                if p.printer_status == "DISCOVERED":
                    p.printer_status = "CONFIGURING"
                if p.test_status == "PENDING" and p.printer_status in ("READY", "BUSY") and not p.has_mismatch:
                    p.is_active = True
                    p.test_status = "SUCCESS"
                    p.last_tested_at = now
                    p.test_message = "Assigned agent confirmed the printer is available."
                p.job_count = rep.jobs or 0
                if rep.supports_color is not None:
                    p.supports_color = rep.supports_color
                if rep.supports_duplex is not None:
                    p.supports_duplex = rep.supports_duplex
                p.last_seen = now

        # 2. Track unregistered discovered printers without auto-modifying Printer table
        for rep in req.printers:
            if not rep.cups_printer_name:
                continue
            rep_key = rep.cups_printer_name.strip().lower()
            is_registered = any(p.cups_printer_name.strip().lower() == rep_key for p in registered_printers)
            if not is_registered:
                disc_id = f"{server.id}::{rep.cups_printer_name.strip()}"
                disc = db.query(DiscoveredPrinter).filter(DiscoveredPrinter.id == disc_id).first()
                if not disc:
                    disc = DiscoveredPrinter(
                        id=disc_id,
                        server_id=server.id,
                        cups_printer_name=rep.cups_printer_name.strip(),
                        ip_address=rep.ip_address,
                        device_uri=rep.device_uri,
                        reported_status=rep.status,
                        reported_jobs=str(rep.jobs or 0),
                        first_seen=now,
                        last_seen=now,
                    )
                    db.add(disc)
                else:
                    disc.ip_address = rep.ip_address or disc.ip_address
                    disc.device_uri = rep.device_uri or disc.device_uri
                    disc.reported_status = rep.status
                    disc.reported_jobs = str(rep.jobs or 0)
                    disc.last_seen = now

    db.commit()
    assignments = [{"cups_printer_name": p.cups_printer_name, "device_uri": p.device_uri}
                   for p in db.query(Printer).filter(Printer.server_id == server.id, Printer.is_enabled == True).all()]
    return HeartbeatResponse(status="OK", server_time=server.last_heartbeat, assignments=assignments)


@router.get("/jobs", response_model=List[AgentJobResponse])
def get_pending_jobs(
    server: PrintServer = Depends(get_authenticated_agent),
    db: Session = Depends(get_db)
):
    return job_service.get_pending_jobs_for_server(db, server.id)


@router.post("/release-kiosk", response_model=AgentReleaseResponse)
@router.post("/release", response_model=AgentReleaseResponse)
def release_job_with_otp(
    req: AgentReleaseRequest,
    request: Request,
    server: PrintServer = Depends(get_authenticated_agent),
    db: Session = Depends(get_db)
):
    client_ip = request.client.host if request.client else "unknown"
    job = otp_service.verify_and_release_job(
        db=db,
        server_id=server.id,
        plaintext_otp=req.otp,
        client_ip=client_ip
    )
    order = db.query(Order).filter(Order.id == job.order_id).first()
    doc = db.query(Document).filter(Document.id == order.document_id).first()

    return AgentReleaseResponse(
        job_id=job.id,
        order_id=order.id,
        status=job.status,
        storage_key=doc.storage_key,
        settings=sanitize_print_settings(order.print_settings)
    )

@router.post("/jobs/{job_id}/status", response_model=MessageResponse)
def update_job_status(
    job_id: str,
    update: AgentJobStatusUpdate,
    server: PrintServer = Depends(get_authenticated_agent),
    db: Session = Depends(get_db)
):
    job_service.update_job_status(
        db=db,
        server_id=server.id,
        job_id=job_id,
        update=update
    )
    return MessageResponse(message="Job status updated successfully.")


@router.post("/jobs/{job_id}/claim")
def claim_job(job_id: str, server: PrintServer = Depends(get_authenticated_agent), db: Session = Depends(get_db)):
    return {"claimed": job_service.claim_job(db, server.id, job_id)}


@router.get("/file/{storage_key:path}")
def download_file_for_agent(
    storage_key: str,
    server: PrintServer = Depends(get_authenticated_agent),
    db: Session = Depends(get_db),
):
    allowed = db.query(Document).join(Order, Order.document_id == Document.id).join(PrintJob, PrintJob.order_id == Order.id).filter(Document.storage_key == storage_key, PrintJob.server_id == server.id, PrintJob.status.in_([PrintJobStatus.RELEASED, PrintJobStatus.PRINTING])).first()
    if not allowed:
        raise AppException(404, "NOT_FOUND", "No released job for this document at this station.")
    path = storage_service.resolve_storage_key(storage_key)
    if not path.exists() or not path.is_file():
        raise AppException(
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="FILE_NOT_FOUND",
            message="Document not found on disk."
        )
    return FileResponse(path=str(path), filename=path.name)
