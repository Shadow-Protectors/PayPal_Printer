import time
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi import status

from app.config.settings import settings
from app.db.models.order import Order, OrderStatus
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.otp import OTP
from app.db.models.document import Document
from app.db.models.payment import Payment, PaymentStatus
from app.utils.crypto import generate_secure_otp, hash_sha256, encrypt_value, decrypt_value
from app.utils.errors import AppException
from app.utils.state_machine import validate_order_transition, validate_job_transition

logger = logging.getLogger("smartprint.security")

# Keep the legacy NOT NULL database column compatible with existing installations.
# Order release codes have no time limit; this value is never used for validation
# or exposed as an expiry in API responses.
LEGACY_NO_EXPIRY_TIMESTAMP = datetime(9999, 12, 31)

class OTPRateLimiter:
    """Thread-safe in-memory sliding-window rate limiter & cooldown manager for OTP verifications."""
    def __init__(self):
        self._lock = threading.Lock()
        self._attempts = {}
        self._cooldowns = {}

    def check_rate_limit(self, key: str, max_attempts: int, window_seconds: int, cooldown_seconds: int) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            # Check active cooldown
            if key in self._cooldowns:
                if now < self._cooldowns[key]:
                    remaining = int(self._cooldowns[key] - now) + 1
                    return False, remaining
                else:
                    del self._cooldowns[key]

            # Clean expired timestamps
            if key in self._attempts:
                dq = self._attempts[key]
                while dq and dq[0] < now - window_seconds:
                    dq.popleft()
                if len(dq) >= max_attempts:
                    self._cooldowns[key] = now + cooldown_seconds
                    return False, cooldown_seconds

            return True, 0

    def record_failed_attempt(self, key: str, max_attempts: int, window_seconds: int, cooldown_seconds: int) -> int:
        now = time.time()
        with self._lock:
            if key not in self._attempts:
                self._attempts[key] = deque()
            dq = self._attempts[key]
            dq.append(now)
            while dq and dq[0] < now - window_seconds:
                dq.popleft()
            if len(dq) >= max_attempts:
                self._cooldowns[key] = now + cooldown_seconds
            return len(dq)

    def reset(self, key: str):
        with self._lock:
            self._attempts.pop(key, None)
            self._cooldowns.pop(key, None)

_otp_rate_limiter = OTPRateLimiter()

class OTPService:
    @staticmethod
    def generate_and_store_otp(db: Session, order_id: str) -> str:
        """
        Generates distinct 6-digit cryptographic OTPs for connected station printers,
        hashes them, stores the primary in the OTP table and both in order.print_settings.
        """
        # Deactivate any previous OTPs for this order
        existing = db.query(OTP).filter(OTP.order_id == order_id, OTP.active == True).all()
        for old in existing:
            old.active = False

        # Reserve every active code, including secondary printer codes. Codes
        # remain valid indefinitely and must not collide with another order.
        reserved_hashes = set()
        for active_otp, active_order in db.query(OTP, Order).join(
            Order, Order.id == OTP.order_id
        ).filter(OTP.active == True).all():
            reserved_hashes.add(active_otp.otp_hash)
            for printer in (active_order.print_settings or {}).get("printer_otps", {}).values():
                if isinstance(printer, dict) and printer.get("active", True):
                    if printer.get("otp_hash"):
                        reserved_hashes.add(printer["otp_hash"])
                    elif printer.get("otp"):
                        reserved_hashes.add(hash_sha256(str(printer["otp"])))

        def unused_code():
            for _ in range(128):
                code = generate_secure_otp(6)
                code_hash = hash_sha256(code)
                if code_hash not in reserved_hashes:
                    reserved_hashes.add(code_hash)
                    return code
            raise AppException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code="CODE_GENERATION_UNAVAILABLE",
                message="Unable to assign a release code. Please try again.",
            )

        otp_p1 = unused_code()
        otp_p2 = unused_code()

        hashed_p1 = hash_sha256(otp_p1)
        encrypted_p1 = encrypt_value(otp_p1)
        hashed_p2 = hash_sha256(otp_p2)
        expires_at = LEGACY_NO_EXPIRY_TIMESTAMP

        otp_record = db.query(OTP).filter(OTP.order_id == order_id).with_for_update().first()
        if otp_record is None:
            otp_record = OTP(order_id=order_id)
            db.add(otp_record)
        otp_record.otp_hash = hashed_p1
        otp_record.encrypted_value = encrypted_p1
        otp_record.expires_at = expires_at
        otp_record.attempt_count = 0
        otp_record.used_at = None
        otp_record.active = True

        # Store dynamic printer OTP structure in Order.print_settings from registered DB printers
        order = db.query(Order).filter(Order.id == order_id).first()
        if order:
            cur_settings = dict(order.print_settings or {})
            
            # Fetch active printers from DB
            from app.db.models.printer import Printer
            db_printers = []
            if order.print_server_id:
                db_printers = db.query(Printer).filter(
                    Printer.server_id == order.print_server_id,
                    Printer.is_enabled == True
                ).all()
            if not order.print_server_id and getattr(order, "department", None):
                from app.db.models.department import Department
                dept_obj = db.query(Department).filter(
                    (Department.name == order.department) | (Department.code == order.department)
                ).first()
                if dept_obj:
                    db_printers = db.query(Printer).filter(
                        Printer.department_id == dept_obj.id,
                        Printer.is_enabled == True
                    ).all()
            # A release code may target only real printers assigned to this station.
            db_printers = [p for p in db_printers if
                (not cur_settings.get("colour") or p.supports_color) and
                (cur_settings.get("sides", "one-sided") == "one-sided" or p.supports_duplex)]
            printer_otps_map = {}
            first_cups = None
            first_name = None
            for idx, p in enumerate(db_printers):
                p_otp = otp_p1 if idx == 0 else (otp_p2 if idx == 1 else unused_code())
                info = {
                    "printer_id": p.id,
                    "printer_name": p.display_name or p.cups_printer_name,
                    "cups_printer_name": p.cups_printer_name,
                    "description": p.description or p.model or "Station printer",
                    "type": "Color" if p.supports_color else "B&W",
                    "badge": p.location or "Station",
                    "otp": p_otp,
                    "otp_hash": hash_sha256(p_otp),
                    "active": True,
                }
                printer_otps_map[p.cups_printer_name] = info
                if first_cups is None:
                    first_cups = p.cups_printer_name
                    first_name = p.display_name or p.cups_printer_name
            cur_settings["printer_otps"] = printer_otps_map
            cur_settings.pop("is_released", None)
            if "cups_printer_name" not in cur_settings or not cur_settings["cups_printer_name"]:
                cur_settings["cups_printer_name"] = first_cups
            if "printer_name" not in cur_settings or not cur_settings["printer_name"]:
                cur_settings["printer_name"] = first_name
            if "printer_switch_count" not in cur_settings:
                cur_settings["printer_switch_count"] = 0
            if "printer_selection_locked" not in cur_settings:
                cur_settings["printer_selection_locked"] = False
            order.print_settings = cur_settings

        db.flush()
        return otp_p1

    @staticmethod
    def get_otp_for_order(db: Session, order_id: str) -> tuple[str, None, dict]:
        otp_record = db.query(OTP).filter(
            OTP.order_id == order_id,
            OTP.active == True
        ).first()

        order = db.query(Order).filter(Order.id == order_id).first()
        settings = dict(order.print_settings or {}) if order else {}
        printer_otps = settings.get("printer_otps", {})

        if not otp_record or not otp_record.encrypted_value:
            if printer_otps:
                selected_printer = settings.get("cups_printer_name") or settings.get("selected_printer")
                if selected_printer and selected_printer in printer_otps:
                    return str(printer_otps[selected_printer].get("otp")), None, printer_otps
                for p_key, p_val in printer_otps.items():
                    if isinstance(p_val, dict) and p_val.get("otp"):
                        return str(p_val["otp"]), None, printer_otps

            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="NOT_FOUND",
                message="No active OTP found for this order."
            )

        plaintext = decrypt_value(otp_record.encrypted_value)
        selected_printer = settings.get("cups_printer_name") or settings.get("selected_printer")
        if selected_printer and printer_otps:
            p_data = printer_otps.get(selected_printer)
            if not p_data:
                for p_key, p_val in printer_otps.items():
                    if isinstance(p_val, dict) and (p_val.get("printer_id") == selected_printer or p_val.get("cups_printer_name") == selected_printer):
                        p_data = p_val
                        break
            if isinstance(p_data, dict) and p_data.get("otp"):
                plaintext = str(p_data["otp"])
            elif printer_otps:
                first_val = next(iter(printer_otps.values()), None)
                if isinstance(first_val, dict) and first_val.get("otp"):
                    plaintext = str(first_val["otp"])

        return plaintext, None, printer_otps

    @staticmethod
    def verify_and_release_job(
        db: Session,
        server_id: str | None = None,
        plaintext_otp: str = "",
        client_ip: str | None = None
    ) -> PrintJob:
        """
        Transactional verification of OTP by print server or kiosk web interface.
        Enforces attempt counting, lockout, cooldowns, and rate limiting across both kiosk
        and agent verification endpoints.
        """
        raw_otp = plaintext_otp.strip()
        rate_key = f"server:{server_id}:ip:{client_ip or 'unknown'}"
        attempt_limit = min(settings.MAX_OTP_ATTEMPTS, settings.OTP_RATE_LIMIT_ATTEMPTS)

        # 0. Cooldown and rate limit check
        allowed, retry_after = _otp_rate_limiter.check_rate_limit(
            rate_key,
            max_attempts=attempt_limit,
            window_seconds=settings.OTP_RATE_LIMIT_WINDOW_SECONDS,
            cooldown_seconds=settings.OTP_COOLDOWN_SECONDS
        )
        if not allowed:
            logger.warning(f"[SECURITY] OTP release rate-limited for {rate_key}. Cooldown: {retry_after}s remaining.")
            raise AppException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                error_code="TOO_MANY_ATTEMPTS",
                message=f"Too many failed OTP attempts. Please wait {retry_after} seconds before trying again."
            )

        hashed_input = hash_sha256(raw_otp)

        # 1. Search candidate by standard OTP table hash
        matching_entry = None
        matched_printer_name = None

        candidates = (
            db.query(OTP, Order, PrintJob, Document)
            .join(Order, Order.id == OTP.order_id)
            .join(PrintJob, PrintJob.order_id == Order.id)
            .join(Document, Document.id == Order.document_id)
            .filter(OTP.otp_hash == hashed_input)
            .order_by(OTP.active.desc(), OTP.id.desc())
            .with_for_update()
            .all()
        )

        if candidates:
            matching_entry = candidates[0]
            ord_obj = matching_entry[1]
            ord_cfg = dict(ord_obj.print_settings or {})
            potps = ord_cfg.get("printer_otps", {})
            for p_cups, p_info in potps.items():
                if isinstance(p_info, dict) and ((p_info.get("otp") == raw_otp) or (p_info.get("otp_hash") == hashed_input)):
                    matched_printer_name = p_info.get("cups_printer_name") or p_cups
                    break
            if not matched_printer_name:
                matched_printer_name = (
                    ord_cfg.get("cups_printer_name")
                    or ord_cfg.get("printer_name")
                    or ord_cfg.get("selected_printer")
                    or "Default_Printer"
                )

        # 2. If not matched in primary OTP row, check active orders' printer_otps dictionary
        if not matching_entry:
            recent_orders = (
                db.query(Order, PrintJob, Document)
                .join(PrintJob, PrintJob.order_id == Order.id)
                .join(Document, Document.id == Order.document_id)
                .filter(Order.status.in_([
                    OrderStatus.WAITING_FOR_OTP,
                    OrderStatus.RELEASED,
                    OrderStatus.PRINTING,
                    OrderStatus.COMPLETED
                ]))
                .order_by(Order.created_at.desc())
                .with_for_update()
                .all()
            )

            for ord_row, jb_row, dc_row in recent_orders:
                cfg = dict(ord_row.print_settings or {})
                potps = cfg.get("printer_otps", {})
                for p_cups, p_info in potps.items():
                    if (p_info.get("otp") == raw_otp) or (p_info.get("otp_hash") == hashed_input):
                        # Found order matching this printer's OTP
                        matched_printer_name = p_info.get("cups_printer_name") or p_cups
                        otp_rec = (
                            db.query(OTP)
                            .filter(OTP.order_id == ord_row.id)
                            .order_by(OTP.id.desc())
                            .first()
                        )
                        if not otp_rec:
                            otp_rec = OTP(
                                order_id=ord_row.id,
                                otp_hash=hashed_input,
                                expires_at=LEGACY_NO_EXPIRY_TIMESTAMP,
                                active=True
                            )
                            db.add(otp_rec)
                            db.flush()
                        matching_entry = (otp_rec, ord_row, jb_row, dc_row)
                        break
                if matching_entry:
                    break

        # 3. Handle failed verification (attempt counter, lockout, and rate limiting)
        if not matching_entry:
            failed_count = _otp_rate_limiter.record_failed_attempt(
                rate_key,
                max_attempts=attempt_limit,
                window_seconds=settings.OTP_RATE_LIMIT_WINDOW_SECONDS,
                cooldown_seconds=settings.OTP_COOLDOWN_SECONDS
            )

            # An unknown code identifies no order. Throttle the requesting station;
            # do not invalidate other customers' paid release codes.
            logger.warning("Invalid release code at %s; failures=%s", rate_key, failed_count)

            if failed_count >= attempt_limit:
                raise AppException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    error_code="TOO_MANY_ATTEMPTS",
                    message=f"Maximum OTP attempts exceeded. Please wait {settings.OTP_COOLDOWN_SECONDS} seconds before trying again."
                )

            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_OTP",
                message="Invalid OTP. Please check the OTP and try again."
            )

        otp_rec, order_rec, job_rec, doc_rec = matching_entry

        if server_id and job_rec.server_id != server_id:
            raise AppException(400, "WRONG_STATION", "Enter this code at the station selected for your order.")

        # 4. Check if order was cancelled
        if order_rec.status == OrderStatus.CANCELLED:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="ORDER_CANCELLED",
                message="This order has been cancelled and its OTP is no longer valid."
            )

        # 5. Check if already completed or released (Crucial Anti-Duplicate Rule)
        order_settings = dict(order_rec.print_settings or {})
        if (
            order_rec.status in [OrderStatus.COMPLETED, OrderStatus.PRINTING]
            or job_rec.status in [PrintJobStatus.COMPLETED, PrintJobStatus.PRINTING]
            or otp_rec.used_at is not None
            or order_settings.get("is_released") is True
        ):
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="ALREADY_PRINTED",
                message="This print job has already been released. Its release codes are no longer valid."
            )

        # 6. Check attempts lockout
        if otp_rec.attempt_count >= settings.MAX_OTP_ATTEMPTS:
            otp_rec.active = False
            db.commit()
            raise AppException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                error_code="TOO_MANY_ATTEMPTS",
                message="Maximum OTP attempts exceeded. Please generate/request a new OTP."
            )

        # 7. Check if inactive
        if not otp_rec.active:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_OTP",
                message="This OTP is inactive or invalid."
            )

        # Idempotency for already released jobs
        if order_rec.status == OrderStatus.RELEASED and job_rec.status == PrintJobStatus.RELEASED:
            return job_rec

        # 7. Verify payment completion
        if order_rec.status == OrderStatus.CREATED:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="PAYMENT_NOT_COMPLETED",
                message="Payment has not been completed for this order."
            )
        payment = db.query(Payment).filter(Payment.order_id == order_rec.id).first()
        if not payment or payment.status != PaymentStatus.CAPTURED:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="PAYMENT_NOT_COMPLETED",
                message="Payment has not been completed for this order."
            )

        # 9. Successful Verification: Reset attempts & clear rate limiter
        otp_rec.attempt_count = 0
        _otp_rate_limiter.reset(rate_key)
        logger.info(f"[SECURITY] OTP successfully verified and released for order {order_rec.id} (Identifier: {rate_key})")

        # Revalidate assignment at release; administrators may have changed it since payment.
        from app.db.models.printer import Printer
        target_printer = matched_printer_name or order_settings.get("cups_printer_name")
        printer = db.query(Printer).filter(
            Printer.server_id == job_rec.server_id,
            Printer.cups_printer_name == target_printer,
            Printer.is_enabled == True,
        ).first()
        if not printer:
            raise AppException(409, "PRINTER_UNAVAILABLE", "The selected printer is no longer assigned or enabled. Contact the attendant.")
        if order_settings.get("printer_selection_locked") and order_settings.get("cups_printer_name") != target_printer:
            raise AppException(400, "INVALID_OTP", "Use the release code for your selected printer.")
        from app.services.printer_availability import available
        from app.db.models.print_server import PrintServer
        station = db.get(PrintServer, job_rec.server_id)
        if not available(printer, station):
            raise AppException(409, "PRINTER_UNAVAILABLE", "Printer unavailable. Your code remains valid; try again when the printer is ready.")
        job_rec.printer_id = printer.id

        # Apply state transitions
        validate_order_transition(order_rec.status, OrderStatus.RELEASED)
        validate_job_transition(job_rec.status, PrintJobStatus.RELEASED)

        now = datetime.now(timezone.utc)

        # Invalidate the primary OTP record
        otp_rec.used_at = now
        otp_rec.active = False

        # Invalidate all printer OTPs in order settings & lock printer selection
        order_settings["cups_printer_name"] = target_printer
        order_settings["printer_name"] = printer.display_name
        order_settings["selected_printer"] = target_printer
        order_settings["is_released"] = True
        order_settings["released_at"] = now.isoformat()
        order_settings["printer_selection_locked"] = True

        if "printer_otps" in order_settings:
            for pkey, pval in order_settings["printer_otps"].items():
                pval["active"] = False
                pval["used_at"] = now.isoformat()
                pval["used_by_this_printer"] = (pkey == target_printer)

        order_rec.print_settings = order_settings
        order_rec.status = OrderStatus.RELEASED
        order_rec.updated_at = now

        job_rec.status = PrintJobStatus.RELEASED
        job_rec.updated_at = now

        db.commit()
        db.refresh(job_rec)
        return job_rec

otp_service = OTPService()
