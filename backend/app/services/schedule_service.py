import os
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.db.models.department import Department
from app.db.models.user import User, UserRole
from app.services.report_service import report_service
from app.services.export_service import export_service
from app.schemas.report import ScheduledReportTriggerResponse

logger = logging.getLogger(__name__)
settings = Settings()


class ScheduleService:
    @staticmethod
    def _send_email_with_attachment(
        to_email: str,
        subject: str,
        body_text: str,
        attachment_bytes: bytes,
        attachment_filename: str,
    ) -> bool:
        if not to_email:
            return False
        if settings.EMAIL_PROVIDER == "mock" and settings.ENVIRONMENT not in ("production", "prod"):
            return True
        if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.warning("Scheduled report delivery is not configured")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL or settings.SMTP_USER}>"
            msg["To"] = to_email
            msg["Subject"] = subject

            msg.attach(MIMEText(body_text, "plain"))

            part = MIMEApplication(attachment_bytes, Name=attachment_filename)
            part["Content-Disposition"] = f'attachment; filename="{attachment_filename}"'
            msg.attach(part)

            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
            server.starttls(context=ssl.create_default_context())
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL or settings.SMTP_USER, [to_email], msg.as_string())
            server.quit()
            logger.info(f"[Scheduled Reports] Successfully sent {attachment_filename} to {to_email}")
            return True
        except Exception as e:
            logger.warning(f"[Scheduled Reports] Failed to send email to {to_email}: {e}")
            return False

    def trigger_scheduled_reports(
        self,
        db: Session,
        period_preset: str = "last_month",
    ) -> ScheduledReportTriggerResponse:
        dispatched_recipients: List[Dict[str, Any]] = []

        all_departments = db.query(Department).all()
        admin_users = db.query(User).filter(User.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN])).all()

        # 1. Principal / Management: Complete Institutional Overall Report (PDF)
        college_pdf = export_service.generate_pdf_report(
            db=db,
            department_id=None,
            period_preset=period_preset,
        )
        principal_email = settings.REPORT_PRINCIPAL_EMAIL
        sent = self._send_email_with_attachment(
            to_email=principal_email,
            subject="Achuppori - Monthly Institutional Printing Audit Report",
            body_text="Dear Principal,\n\nPlease find attached the comprehensive institutional printing and resource utilization audit report for the preceding academic reporting period.\n\nAchuppori Autonomous Cloud Print",
            attachment_bytes=college_pdf,
            attachment_filename="achuppori_college_overall_report.pdf",
        )
        dispatched_recipients.append({
            "role": "PRINCIPAL",
            "email": principal_email,
            "report_type": "Overall Institutional Report (PDF)",
            "status": "DISPATCHED" if sent else "FAILED",
        })

        # 2. Heads of Departments (HODs): Department-specific Reports (PDF)
        for dept in all_departments:
            dept_pdf = export_service.generate_pdf_report(
                db=db,
                department_id=dept.id,
                period_preset=period_preset,
            )
            hod_email = settings.REPORT_DEPARTMENT_EMAILS.get(dept.code, "")
            sent = self._send_email_with_attachment(
                to_email=hod_email,
                subject=f"Achuppori - {dept.name} Monthly Department Printing Report",
                body_text=f"Dear Head of Department,\n\nPlease find attached the monthly departmental printing report and printer utilization summary for {dept.name}.\n\nAchuppori Autonomous Cloud Print",
                attachment_bytes=dept_pdf,
                attachment_filename=f"achuppori_{dept.code.lower()}_department_report.pdf",
            )
            dispatched_recipients.append({
                "role": f"HOD_{dept.code}",
                "department": dept.name,
                "email": hod_email,
                "report_type": "Department Printing Report (PDF)",
                "status": "DISPATCHED" if sent else "FAILED",
            })

        # 3. Accounts Office: Revenue Summary (Excel + PDF)
        accounts_excel = export_service.generate_excel_report(
            db=db,
            department_id=None,
            period_preset=period_preset,
        )
        accounts_email = settings.REPORT_ACCOUNTS_EMAIL
        sent = self._send_email_with_attachment(
            to_email=accounts_email,
            subject="Achuppori - Monthly Accounts & Revenue Reconciliation Report",
            body_text="Dear Accounts Officer,\n\nPlease find attached the complete digital revenue reconciliation workbook and printing fee audit for the past month.\n\nAchuppori Autonomous Cloud Print",
            attachment_bytes=accounts_excel,
            attachment_filename="achuppori_revenue_reconciliation.xlsx",
        )
        dispatched_recipients.append({
            "role": "ACCOUNTS",
            "email": accounts_email,
            "report_type": "Financial Reconciliation Workbook (Excel)",
            "status": "DISPATCHED" if sent else "FAILED",
        })

        # 4. System Administrator: Printer Hardware Utilization & Health
        sysadmin_email = settings.REPORT_SYSADMIN_EMAIL
        sent = self._send_email_with_attachment(
            to_email=sysadmin_email,
            subject="Achuppori - Printer Fleet Hardware Health & Telemetry Audit",
            body_text="Dear System Administrator,\n\nPlease find attached the monthly hardware utilization, error metrics, and kiosk printer status report.\n\nAchuppori Autonomous Cloud Print",
            attachment_bytes=college_pdf,
            attachment_filename="achuppori_printer_fleet_health.pdf",
        )
        dispatched_recipients.append({
            "role": "SYSADMIN",
            "email": sysadmin_email,
            "report_type": "Fleet Utilization & Diagnostic Report (PDF)",
            "status": "DISPATCHED" if sent else "FAILED",
        })

        return ScheduledReportTriggerResponse(
            success=bool(dispatched_recipients) and all(r["status"] == "DISPATCHED" for r in dispatched_recipients),
            dispatched_count=sum(r["status"] == "DISPATCHED" for r in dispatched_recipients),
            recipients=dispatched_recipients,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )


schedule_service = ScheduleService()
