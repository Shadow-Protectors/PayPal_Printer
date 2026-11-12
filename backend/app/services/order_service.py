import io
import uuid
import hashlib
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from fastapi import status
from pypdf import PdfWriter, PdfReader
from PIL import Image

import app.db.base
from app.db.models.order import Order, OrderStatus
from app.db.models.document import Document, DocumentStatus
from app.db.models.print_server import PrintServer, PrintServerStatus
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.otp import OTP
from app.config.settings import settings
from app.schemas.order import OrderCreateRequest, OrderItemConfig, PrintSettingsSchema
from app.services.pricing_service import pricing_service
from app.services.storage_service import storage_service
from app.services.refund_service import refund_service
from app.utils.errors import AppException
from app.utils.state_machine import validate_order_transition, validate_job_transition

class OrderService:
    @staticmethod
    def create_order(
        db: Session,
        req: OrderCreateRequest,
        user_id: Optional[int] = None,
        session_token: Optional[str] = None
    ) -> Order:
        roll_number = req.rollNumber
        department = req.department
        if user_id:
            from app.db.models.user import User
            usr = db.query(User).filter(User.id == user_id).first()
            if usr:
                if not usr.is_active:
                    raise AppException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        error_code="USER_INACTIVE",
                        message="Your user account has been deactivated. Orders cannot be created."
                    )
                roll_number = roll_number or usr.roll_number
                department = department or usr.department

        # Validate print server
        server = db.query(PrintServer).filter(PrintServer.id == req.printServerId).first()
        if not server:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="NOT_FOUND",
                message="Print server station not found."
            )

        if server.status == PrintServerStatus.DISABLED or not server.is_enabled:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="PRINT_SERVER_DISABLED",
                message="This print server station is currently disabled."
            )

        if settings.ENVIRONMENT.lower() in ("production", "prod"):
            if server.status == PrintServerStatus.OFFLINE:
                raise AppException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_code="PRINT_SERVER_OFFLINE",
                    message="This print server station is currently offline."
                )
            heartbeat = server.last_heartbeat
            if heartbeat and heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            if not heartbeat or heartbeat < datetime.now(timezone.utc) - timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS):
                raise AppException(409, "PRINT_SERVER_OFFLINE", "The station has not reported a recent heartbeat.")

        if server.status == PrintServerStatus.MAINTENANCE:
            raise AppException(409, "STATION_UNAVAILABLE", "This station is under maintenance.")
        from app.db.models.printer import Printer
        from app.services.printer_availability import available
        available_printers = db.query(Printer).filter(Printer.server_id == server.id, Printer.is_enabled == True).all()
        if settings.ENVIRONMENT.lower() in ("production", "prod"):
            available_printers = [p for p in available_printers if available(p, server)]
            if not available_printers:
                raise AppException(409, "PRINTER_UNAVAILABLE", "No printer is currently available at this station.")
        elif not available_printers:
            dummy_printer = Printer(
                id="printer_01",
                server_id=server.id,
                cups_printer_name="campus_laser_01",
                display_name="Campus Laser #1",
                supports_color=True,
                supports_duplex=True,
                is_enabled=True,
                is_active=True,
                printer_status="READY"
            )
            db.add(dummy_printer)
            db.commit()
            available_printers = [dummy_printer]

        # Determine items to process
        items_to_process: List[OrderItemConfig] = []
        if req.items and len(req.items) > 0:
            items_to_process = req.items
        elif req.documentId:
            items_to_process = [
                OrderItemConfig(
                    documentId=req.documentId,
                    settings=req.settings or PrintSettingsSchema()
                )
            ]
        else:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="MISSING_DOCUMENT",
                message="No document provided in order request."
            )

        for item in items_to_process:
            if not any((not item.settings.colour or p.supports_color) and
                       (item.settings.sides == "one-sided" or p.supports_duplex) for p in available_printers):
                raise AppException(400, "UNSUPPORTED_OPTIONS", "No assigned printer supports the selected color and duplex options.")

        # Case 1: Single Document Order
        if len(items_to_process) == 1:
            item = items_to_process[0]
            query = db.query(Document).filter(Document.id == item.documentId)
            if user_id is not None:
                query = query.filter((Document.user_id == user_id) | (Document.user_id == None))
            document = query.first()

            if not document:
                raise AppException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_code="NOT_FOUND",
                    message="Document not found."
                )

            if document.status != DocumentStatus.ACTIVE:
                raise AppException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_code="INVALID_STATE",
                    message=f"Document status is {document.status.value}, cannot be printed."
                )

            if document.expires_at:
                doc_expires = document.expires_at
                if doc_expires.tzinfo is None:
                    doc_expires = doc_expires.replace(tzinfo=timezone.utc)
                if doc_expires < datetime.now(timezone.utc):
                    raise AppException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        error_code="DOCUMENT_EXPIRED",
                        message="Document has expired."
                    )

            selected_pages = pricing_service.parse_and_validate_page_range(
                item.settings.pageRange,
                document.page_count
            )
            total_pages = len(selected_pages)
            if total_pages * item.settings.copies > 1000:
                raise AppException(413, "ORDER_TOO_LARGE", "An order may contain at most 1000 printed pages including copies.")

            amount = pricing_service.calculate_price(
                selected_pages_count=total_pages,
                copies=item.settings.copies,
                is_colour=item.settings.colour
            )

            order_id = f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

            single_settings = item.settings.model_dump(by_alias=True)
            if session_token:
                single_settings["session_token"] = session_token
            notification_email = req.email.strip().lower() if getattr(req, "email", None) else None
            if not notification_email and user_id:
                from app.db.models.user import User
                usr = db.get(User, user_id)
                if usr and usr.email:
                    notification_email = usr.email
            if notification_email:
                single_settings["notification_email"] = notification_email

            order = Order(
                id=order_id,
                user_id=user_id,
                roll_number=roll_number,
                department=department,
                document_id=document.id,
                print_server_id=server.id,
                print_settings=single_settings,
                total_pages=total_pages,
                copies=item.settings.copies,
                amount=amount,
                currency="INR",
                status=OrderStatus.CREATED,
                created_at=datetime.now(timezone.utc)
            )
            db.add(order)
            db.commit()
            db.refresh(order)
            return order

        # Case 2: Multi-Document Order (Merge all documents and calculate total sum)
        total_amount = 0.0
        total_print_pages = 0
        documents_for_merge = []
        items_summary = []
        any_colour = False

        for item in items_to_process:
            query = db.query(Document).filter(Document.id == item.documentId)
            if user_id is not None:
                query = query.filter((Document.user_id == user_id) | (Document.user_id == None))
            doc = query.first()

            if not doc:
                raise AppException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_code="NOT_FOUND",
                    message=f"Document {item.documentId} not found."
                )

            if doc.status != DocumentStatus.ACTIVE:
                raise AppException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_code="INVALID_STATE",
                    message=f"Document '{doc.original_filename}' is not active."
                )

            selected_pages = pricing_service.parse_and_validate_page_range(
                item.settings.pageRange,
                doc.page_count
            )
            item_pages = len(selected_pages)
            item_price = pricing_service.calculate_price(
                selected_pages_count=item_pages,
                copies=item.settings.copies,
                is_colour=item.settings.colour,
                base_fee=0
            )

            total_amount += item_price
            total_print_pages += (item_pages * item.settings.copies)
            if total_print_pages > 1000:
                raise AppException(413, "ORDER_TOO_LARGE", "An order may contain at most 1000 printed pages including copies.")
            if item.settings.colour:
                any_colour = True

            doc_path = storage_service.resolve_storage_key(doc.storage_key)
            item_sides = getattr(item.settings, 'sides', 'one-sided') or 'one-sided'
            item_orient = getattr(item.settings, 'orientation', 'portrait') or 'portrait'
            item_paper = getattr(item.settings, 'paperSize', 'A4') or 'A4'
            documents_for_merge.append({
                "path": doc_path,
                "pages": selected_pages,
                "copies": item.settings.copies,
                "sides": item_sides,
                "orientation": item_orient,
                "paper_size": item_paper,
                "is_image": doc.mime_type.startswith("image/") or doc_path.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]
            })
            items_summary.append({
                "document_id": doc.id,
                "filename": doc.original_filename,
                "pages": item_pages,
                "copies": item.settings.copies,
                "colour": item.settings.colour,
                "sides": item_sides,
                "orientation": item_orient,
                "paper_size": item_paper,
                "amount": item_price
            })

        order_id = f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        # Combine documents into single unified PDF for physical and autonomous kiosk printing
        combined_doc_id = f"DOC-COMBINED-{uuid.uuid4().hex[:8].upper()}"
        target_combined_rel = f"documents/combined_{order_id}.pdf"
        target_combined_path = storage_service.storage_root / target_combined_rel
        target_combined_path.parent.mkdir(parents=True, exist_ok=True)

        any_duplex = any(d["sides"] in ["two-sided-long-edge", "two-sided-short-edge", "duplex"] for d in documents_for_merge)

        writer = PdfWriter()
        for doc_item in documents_for_merge:
            f_path = doc_item["path"]
            sel_pages = doc_item["pages"]
            copies = doc_item["copies"]
            doc_duplex = doc_item["sides"] in ["two-sided-long-edge", "two-sided-short-edge", "duplex"]
            orientation = doc_item["orientation"].lower()

            for _ in range(copies):
                # If printer is printing duplex, ensure new document copy starts on a new physical sheet (odd page)
                if any_duplex and len(writer.pages) % 2 != 0:
                    writer.add_blank_page()

                if doc_item["is_image"]:
                    with Image.open(f_path) as img:
                        if orientation == "landscape" and img.width < img.height:
                            img = img.rotate(90, expand=True)
                        elif orientation == "portrait" and img.width > img.height:
                            img = img.rotate(90, expand=True)
                        rgb_img = img.convert("RGB")
                        buf = io.BytesIO()
                        rgb_img.save(buf, format="PDF")
                        buf.seek(0)
                        img_reader = PdfReader(buf)
                        for p in img_reader.pages:
                            writer.add_page(p)
                            if any_duplex and not doc_duplex:
                                writer.add_blank_page()
                else:
                    reader = PdfReader(str(f_path))
                    t_pages = len(reader.pages)
                    pages_to_add = sel_pages if sel_pages else list(range(1, t_pages + 1))
                    for p_num in pages_to_add:
                        if 1 <= p_num <= t_pages:
                            p = reader.pages[p_num - 1]
                            w = float(p.mediabox.width)
                            h = float(p.mediabox.height)
                            if orientation == "landscape" and w < h:
                                p.rotate(90)
                            elif orientation == "portrait" and w > h:
                                p.rotate(90)
                            writer.add_page(p)
                            if any_duplex and not doc_duplex:
                                writer.add_blank_page()

        with open(target_combined_path, "wb") as f_out:
            writer.write(f_out)

        file_bytes = target_combined_path.read_bytes()
        sha256 = hashlib.sha256(file_bytes).hexdigest()

        # Register merged document in DB
        merged_document = Document(
            id=combined_doc_id,
            user_id=user_id,
            session_token=session_token,
            original_filename=f"Combined_{len(items_to_process)}_Documents.pdf",
            stored_filename=f"combined_{order_id}.pdf",
            storage_key=target_combined_rel,
            mime_type="application/pdf",
            file_size=len(file_bytes),
            sha256=sha256,
            page_count=len(writer.pages),
            status=DocumentStatus.ACTIVE,
            created_at=datetime.now(timezone.utc)
        )
        db.add(merged_document)
        db.commit()

        # Save order with combined document and total amount
        combined_settings = req.settings.model_dump(by_alias=True) if req.settings else {}
        combined_settings["colour"] = any_colour
        combined_settings["copies"] = 1
        combined_settings["sides"] = "two-sided-long-edge" if any_duplex else "one-sided"
        combined_settings["pageRange"] = "all"
        combined_settings["page_range"] = "all"
        combined_settings["items"] = items_summary
        if session_token:
            combined_settings["session_token"] = session_token
        notification_email = req.email.strip().lower() if getattr(req, "email", None) else None
        if not notification_email and user_id:
            from app.db.models.user import User
            usr = db.get(User, user_id)
            if usr and usr.email:
                notification_email = usr.email
        if notification_email:
            combined_settings["notification_email"] = notification_email

        order = Order(
            id=order_id,
            user_id=user_id,
            roll_number=roll_number,
            department=department,
            document_id=merged_document.id,
            print_server_id=server.id,
            print_settings=combined_settings,
            total_pages=len(writer.pages),
            copies=1,
            amount=round(total_amount + settings.BASE_FEE, 2),
            currency="INR",
            status=OrderStatus.CREATED,
            created_at=datetime.now(timezone.utc)
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order

    @staticmethod
    def cancel_order(
        db: Session,
        order_id: str,
        user_id: Optional[int] = None,
        session_token: Optional[str] = None,
        reason: str = "User requested cancellation"
    ) -> Dict[str, Any]:
        """
        Transactional cancellation of an order.
        - For UNPAID (CREATED) orders: cancels order immediately and marks documents for cleanup.
        - For PAID orders (WAITING_FOR_OTP, PAID, JOB_QUEUED): atomically invalidates OTPs,
          cancels queued print job, marks documents for cleanup, and triggers full refund.
        - For PRINTING, RELEASED, or COMPLETED orders: raises 400 error as physical printing
          cannot be reversed.
        """
        order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
        if not order:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="NOT_FOUND",
                message="Order not found."
            )

        # Validate non-cancellable states
        if order.status in [OrderStatus.RELEASED, OrderStatus.PRINTING, OrderStatus.COMPLETED]:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="ORDER_NOT_CANCELLABLE",
                message="Order cannot be cancelled because printing has already started or completed."
            )

        if order.status == OrderStatus.CANCELLED:
            return {
                "status": "SUCCESS",
                "orderId": order.id,
                "orderStatus": "CANCELLED",
                "refundRequired": False,
                "message": "Order is already cancelled."
            }

        if order.status == OrderStatus.REFUNDED:
            return {
                "status": "SUCCESS",
                "orderId": order.id,
                "orderStatus": "REFUNDED",
                "refundRequired": False,
                "message": "Order is already cancelled and refunded."
            }

        now = datetime.now(timezone.utc)

        # Helper to flag documents for cleanup
        def _flag_documents_cleanup():
            doc = db.query(Document).filter(Document.id == order.document_id).first()
            if doc and doc.status == DocumentStatus.ACTIVE:
                doc.status = DocumentStatus.CLEANUP_PENDING
            items = (order.print_settings or {}).get("items", [])
            for it in items:
                c_id = it.get("document_id")
                if c_id:
                    c_doc = db.query(Document).filter(Document.id == c_id).first()
                    if c_doc and c_doc.status == DocumentStatus.ACTIVE:
                        c_doc.status = DocumentStatus.CLEANUP_PENDING

        # Case 1: Unpaid Order
        if order.status == OrderStatus.CREATED:
            validate_order_transition(order.status, OrderStatus.CANCELLED)
            order.status = OrderStatus.CANCELLED
            order.updated_at = now
            _flag_documents_cleanup()
            db.commit()
            db.refresh(order)
            return {
                "status": "SUCCESS",
                "orderId": order.id,
                "orderStatus": "CANCELLED",
                "refundRequired": False,
                "message": "Order cancelled successfully."
            }

        # Case 2: Paid Pre-Release Order (WAITING_FOR_OTP, PAID, JOB_QUEUED)
        # 1. Atomically invalidate all active OTPs
        otps = db.query(OTP).filter(OTP.order_id == order.id, OTP.active == True).all()
        for o in otps:
            o.active = False
        cur_settings = dict(order.print_settings or {})
        if "printer_otps" in cur_settings:
            for p_key, p_info in cur_settings["printer_otps"].items():
                if isinstance(p_info, dict):
                    p_info["active"] = False
            order.print_settings = cur_settings

        # 2. Cancel queued print job
        job = db.query(PrintJob).filter(PrintJob.order_id == order.id).with_for_update().first()
        if job:
            if job.status in [PrintJobStatus.RELEASED, PrintJobStatus.PRINTING, PrintJobStatus.COMPLETED]:
                raise AppException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_code="ORDER_NOT_CANCELLABLE",
                    message="Print job has already started on the physical printer."
                )
            validate_job_transition(job.status, PrintJobStatus.CANCELLED)
            job.status = PrintJobStatus.CANCELLED
            job.error_message = reason
            job.completed_at = now
            job.updated_at = now

        # 3. Transition order status
        validate_order_transition(order.status, OrderStatus.CANCELLED)
        order.status = OrderStatus.CANCELLED
        order.updated_at = now
        _flag_documents_cleanup()
        db.flush()

        # 4. Process full automated refund
        refund = refund_service.process_refund(
            db=db,
            order_id=order.id,
            reason=reason or "Customer cancelled order before print release"
        )

        db.commit()
        db.refresh(order)

        try:
            from app.services.email_service import email_service
            email_service.notify_order_status(db, order, OrderStatus.CANCELLED)
        except Exception:
            pass

        return {
            "status": "SUCCESS",
            "orderId": order.id,
            "orderStatus": order.status.value,
            "refundRequired": True,
            "refundId": refund.id,
            "razorpayRefundId": refund.razorpay_refund_id,
            "amount": float(refund.amount),
            "refundStatus": refund.status.value,
            "message": "Order cancelled. Refund status: " + refund.status.value
        }

    @staticmethod
    def get_orders_for_user(db: Session, user_id: int) -> List[Order]:
        return db.query(Order).filter(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(50).all()

order_service = OrderService()
