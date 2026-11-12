from datetime import datetime, timezone
from typing import List, Dict, Any
import logging
from sqlalchemy.orm import Session
from sqlalchemy import update as sql_update
from fastapi import status

from app.config.settings import settings
from app.db.models.order import Order, OrderStatus
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.document import Document, DocumentStatus
from app.schemas.agent import AgentJobResponse, AgentJobStatusUpdate
from app.schemas.order import sanitize_print_settings
from app.services.refund_service import refund_service
from app.utils.errors import AppException
from app.utils.state_machine import validate_job_transition, validate_order_transition

class JobService:
    @staticmethod
    def claim_job(db: Session, server_id: str, job_id: str) -> bool:
        candidate = db.query(PrintJob).filter(PrintJob.id == job_id, PrintJob.server_id == server_id).first()
        if not candidate:
            return False
        order = db.query(Order).filter(Order.id == candidate.order_id).with_for_update().populate_existing().first()
        if not order:
            return False
        # A conditional UPDATE arbitrates duplicate pollers, kiosk threads, and
        # restarted agents before any irreversible CUPS submission.
        result = db.execute(sql_update(PrintJob).where(
            PrintJob.id == job_id, PrintJob.server_id == server_id,
            PrintJob.status == PrintJobStatus.RELEASED,
        ).values(status=PrintJobStatus.PRINTING, updated_at=datetime.now(timezone.utc)))
        if result.rowcount != 1:
            db.commit()
            return False
        job = db.get(PrintJob, job_id)
        order = db.get(Order, job.order_id)
        order.status = OrderStatus.PRINTING
        order.updated_at = datetime.now(timezone.utc)
        db.commit()
        try:
            from app.services.email_service import email_service
            email_service.notify_order_status(db, order, OrderStatus.PRINTING)
        except Exception:
            pass
        return True

    @staticmethod
    def get_pending_jobs_for_server(db: Session, server_id: str) -> List[AgentJobResponse]:
        """
        Returns all RELEASED jobs for the authenticated print server.
        """
        results = (
            db.query(PrintJob, Order, Document)
            .join(Order, Order.id == PrintJob.order_id)
            .join(Document, Document.id == Order.document_id)
            .filter(
                PrintJob.server_id == server_id,
                PrintJob.status == PrintJobStatus.RELEASED
            )
            .all()
        )

        job_responses = []
        for job, order, doc in results:
            job_responses.append(AgentJobResponse(
                job_id=job.id,
                order_id=order.id,
                storage_key=doc.storage_key,
                settings=sanitize_print_settings(order.print_settings)
            ))
        return job_responses

    @staticmethod
    def update_job_status(
        db: Session,
        server_id: str,
        job_id: str,
        update: AgentJobStatusUpdate
    ) -> PrintJob:
        candidate = db.query(PrintJob).filter(
            PrintJob.id == job_id,
            PrintJob.server_id == server_id
        ).first()

        if candidate:
            db.query(Order).filter(Order.id == candidate.order_id).with_for_update().populate_existing().first()
        job = db.query(PrintJob).filter(
            PrintJob.id == job_id, PrintJob.server_id == server_id
        ).with_for_update().populate_existing().first()

        if not job:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="NOT_FOUND",
                message="Print job not found for this print server."
            )

        if update.eventId and job.last_status_event == update.eventId:
            return job
        if job.status == PrintJobStatus.FINAL_FAILED and update.status == PrintJobStatus.FAILED:
            return job

        order = db.query(Order).filter(Order.id == job.order_id).with_for_update().first()
        if not order:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="NOT_FOUND",
                message="Associated order not found."
            )

        target_status = update.status
        if target_status not in (PrintJobStatus.PRINTING, PrintJobStatus.COMPLETED, PrintJobStatus.FAILED):
            raise AppException(400, "INVALID_STATE", "Agents may report printing, completed, or failed jobs only.")
        validate_job_transition(job.status, target_status)

        now = datetime.now(timezone.utc)
        job.updated_at = now
        job.last_status_event = update.eventId
        if update.cupsJobId:
            job.cups_job_id = update.cupsJobId

        if target_status == PrintJobStatus.PRINTING:
            job.status = PrintJobStatus.PRINTING
            if update.cupsJobId:
                job.cups_job_id = update.cupsJobId
            job.error_code = update.errorCode
            job.error_message = update.message
            if order.status == OrderStatus.RELEASED:
                validate_order_transition(order.status, OrderStatus.PRINTING)
                order.status = OrderStatus.PRINTING
                order.updated_at = now

        elif target_status == PrintJobStatus.COMPLETED:
            job.status = PrintJobStatus.COMPLETED
            job.completed_at = now
            job.error_code = None
            job.error_message = None
            if order.status in [OrderStatus.PRINTING, OrderStatus.RELEASED, OrderStatus.WAITING_FOR_OTP]:
                validate_order_transition(order.status, OrderStatus.COMPLETED)
                order.status = OrderStatus.COMPLETED
                order.updated_at = now

            # Document can now be marked CLEANUP_PENDING
            doc = db.query(Document).filter(Document.id == order.document_id).first()
            if doc and doc.status == DocumentStatus.ACTIVE:
                doc.status = DocumentStatus.CLEANUP_PENDING

        elif target_status == PrintJobStatus.FAILED:
            job.error_code = update.errorCode
            job.error_message = update.message

            if update.errorCode == "FILE_NOT_FOUND" and not job.cups_job_id and job.retry_count < settings.MAX_PRINT_RETRIES:
                job.retry_count += 1
                job.status = PrintJobStatus.RELEASED
            else:
                job.status = PrintJobStatus.FINAL_FAILED
                job.completed_at = now
                if order.status in [OrderStatus.RELEASED, OrderStatus.PRINTING]:
                    validate_order_transition(order.status, OrderStatus.FAILED)
                    order.status = OrderStatus.FAILED
                    order.updated_at = now

                # Trigger automatic refund for final failure
                try:
                    refund_service.process_refund(
                        db=db,
                        order_id=order.id,
                        reason=update.message or "Print failed after retries"
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Refund processing failed for order %s, job %s, station %s",
                        order.id, job.id, server_id)

        db.commit()
        db.refresh(job)

        try:
            from app.services.email_service import email_service
            extra_info = {}
            if target_status == PrintJobStatus.FAILED:
                extra_info["error_message"] = update.message or job.error_message
            email_service.notify_order_status(db, order, order.status, extra_info=extra_info)
        except Exception:
            pass

        return job

job_service = JobService()
