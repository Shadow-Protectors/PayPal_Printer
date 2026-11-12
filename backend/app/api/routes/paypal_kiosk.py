import os
import uuid
import random
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.config.settings import settings
from app.config.security import hash_token
from app.services.paypal_service import paypal_service
from app.services.ai_optimizer import ai_optimizer

from app.db.models.order import Order, OrderStatus
from app.db.models.document import Document, DocumentStatus
from app.db.models.print_server import PrintServer, PrintServerStatus
from app.db.models.printer import Printer
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.otp import OTP
from app.db.models.print_job import PrintJob, PrintJobStatus

logger = logging.getLogger("smartprint.kiosk")
router = APIRouter(prefix="/api/kiosk", tags=["PayPal Kiosk"])

DEFAULT_STATION_ID = "kiosk_station_01"

def _get_or_create_default_station(db: Session) -> PrintServer:
    station = db.query(PrintServer).filter(PrintServer.id == DEFAULT_STATION_ID).first()
    if not station:
        station = PrintServer(
            id=DEFAULT_STATION_ID,
            name="Main Campus Kiosk #1",
            location="Library Ground Floor",
            device_token_hash=hash_token("kiosk_internal_device_token"),
            status=PrintServerStatus.ONLINE,
            is_enabled=True
        )
        db.add(station)
        db.commit()
        db.refresh(station)
    return station

class CreateOrderRequest(BaseModel):
    file_id: str
    mode: str = "summary"  # "summary" or "full"
    currency: str = "USD"

class CaptureOrderRequest(BaseModel):
    paypal_order_id: str

class ReleaseCodeRequest(BaseModel):
    release_code: str

@router.get("/config")
def get_kiosk_config():
    """Return public PayPal Sandbox client configuration for frontend SDK."""
    client_id = os.getenv("PAYPAL_CLIENT_ID", "")
    return {
        "client_id": client_id,
        "currency": "USD",
        "is_configured": paypal_service.is_configured()
    }

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Accepts PDF upload, analyzes page count, applies AI optimization (with fallback),
    and computes server-authoritative pricing options.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    upload_dir = Path(settings.STORAGE_ROOT) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_id = f"doc_{uuid.uuid4().hex[:12]}"
    saved_path = upload_dir / f"{file_id}_{file.filename}"
    
    content = await file.read()
    with open(saved_path, "wb") as f:
        f.write(content)

    # Run AI optimization
    summary_dir = Path(settings.STORAGE_ROOT) / "summaries"
    opt_result = ai_optimizer.optimize_document(str(saved_path), str(summary_dir))
    
    original_pages = opt_result["original_pages"]
    summary_pages = opt_result["summary_pages"]
    
    # Pricing: $0.10 per page
    rate = getattr(settings, "PER_PAGE_RATE", 0.10)
    full_price = f"{(original_pages * rate):.2f}"
    summary_price = f"{(summary_pages * rate):.2f}"
    
    # Persist Document record
    _get_or_create_default_station(db)
    doc_record = Document(
        id=file_id,
        original_filename=file.filename,
        stored_filename=saved_path.name,
        storage_key=str(saved_path),
        mime_type="application/pdf",
        file_size=len(content),
        sha256=hash_token(content.decode("latin1", errors="ignore")),
        page_count=original_pages,
        status=DocumentStatus.ACTIVE
    )
    db.add(doc_record)
    db.commit()

    return {
        "file_id": file_id,
        "filename": file.filename,
        "original_pages": original_pages,
        "full_price": full_price,
        "summary_pages": summary_pages,
        "summary_price": summary_price,
        "savings_percent": opt_result["savings_percent"],
        "ai_generated": opt_result["ai_success"],
        "currency": "USD"
    }

@router.post("/create-order")
async def create_paypal_kiosk_order(
    req: CreateOrderRequest,
    db: Session = Depends(get_db)
):
    """
    Server-authoritative price calculation:
    Calculates exact price based on server's stored document pages.
    Calls PayPal Sandbox to generate order.
    """
    doc = db.query(Document).filter(Document.id == req.file_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    rate = getattr(settings, "PER_PAGE_RATE", 0.10)
    
    if req.mode == "summary":
        pages = max(1, doc.page_count // 3)
        amount = f"{(pages * rate):.2f}"
        desc = f"SmartPrint AI Summary ({pages} pgs) for {doc.original_filename}"
    else:
        pages = doc.page_count
        amount = f"{(pages * rate):.2f}"
        desc = f"SmartPrint Full Print ({pages} pgs) for {doc.original_filename}"

    # Call PayPal Sandbox API
    paypal_order = paypal_service.create_order(
        amount=amount,
        currency=req.currency,
        description=desc
    )
    paypal_order_id = paypal_order["id"]

    # Save pending Order
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    station = _get_or_create_default_station(db)
    
    order = Order(
        id=order_id,
        document_id=doc.id,
        print_server_id=station.id,
        print_settings={
            "mode": req.mode,
            "pages": pages,
            "paypal_order_id": paypal_order_id,
            "filename": doc.original_filename
        },
        total_pages=pages,
        copies=1,
        amount=amount,
        currency=req.currency,
        status=OrderStatus.CREATED
    )
    db.add(order)
    
    # Save pending payment entry
    payment = Payment(
        id=f"PAY-{uuid.uuid4().hex[:8].upper()}",
        order_id=order.id,
        razorpay_order_id=paypal_order_id,  # reused column for gateway order id
        amount=amount,
        currency=req.currency,
        status=PaymentStatus.PENDING,
        raw_payload=paypal_order
    )
    db.add(payment)
    db.commit()

    return {
        "order_id": order_id,
        "paypal_order_id": paypal_order_id,
        "amount": amount,
        "currency": req.currency,
        "pages": pages,
        "mode": req.mode
    }

@router.post("/capture-order")
async def capture_paypal_kiosk_order(
    req: CaptureOrderRequest,
    db: Session = Depends(get_db)
):
    """
    Idempotent PayPal capture & verification:
    1. Checks if already paid (returns existing PIN if so).
    2. Calls PayPal Capture endpoint.
    3. Verifies top-level & capture status is COMPLETED, and amount matches server price.
    4. Generates single-use 6-digit release PIN expiring in 30 minutes.
    5. Queues print job.
    """
    payment = db.query(Payment).filter(Payment.razorpay_order_id == req.paypal_order_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Order with this PayPal ID not found.")

    order = db.query(Order).filter(Order.id == payment.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Associated order not found.")

    # Idempotency check: if already completed, return existing PIN
    if order.status == OrderStatus.PAID:
        existing_otp = db.query(OTP).filter(OTP.order_id == order.id).first()
        raw_pin = existing_otp.encrypted_value if existing_otp else "REPRINT"
        return {
            "status": "PAID",
            "message": "Order already verified and paid.",
            "release_code": raw_pin,
            "expires_in_minutes": 30,
            "job_status": "QUEUED",
            "order_id": order.id
        }

    # Execute PayPal Capture
    capture_data = paypal_service.capture_order(req.paypal_order_id)
    
    # Server-side verification
    is_valid = paypal_service.verify_capture(
        capture_data,
        expected_amount=str(order.amount),
        expected_currency=order.currency
    )
    
    if not is_valid:
        payment.status = PaymentStatus.FAILED
        payment.raw_payload = capture_data
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="PayPal payment verification failed. Status not COMPLETED or amount tampered."
        )

    # Generate 6-digit PIN (e.g. 839-104)
    raw_pin = f"{random.randint(100, 999)}-{random.randint(100, 999)}"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=30)
    
    # Store OTP
    otp_record = OTP(
        order_id=order.id,
        otp_hash=hash_token(raw_pin.replace("-", "")),
        encrypted_value=raw_pin,
        expires_at=expires_at,
        active=True
    )
    db.add(otp_record)

    # Update Order & Payment
    order.status = OrderStatus.PAID
    payment.status = PaymentStatus.CAPTURED
    payment.razorpay_payment_id = capture_data.get("id", f"CAP-{req.paypal_order_id}")
    payment.raw_payload = capture_data

    # Create PrintJob in QUEUED status
    station = _get_or_create_default_station(db)
    print_job = PrintJob(
        id=f"job_{uuid.uuid4().hex[:10]}",
        order_id=order.id,
        server_id=station.id,
        status=PrintJobStatus.QUEUED
    )
    db.add(print_job)
    db.commit()

    return {
        "status": "PAID",
        "message": "Payment verified via PayPal Sandbox. Document queued for campus kiosk.",
        "release_code": raw_pin,
        "expires_in_minutes": 30,
        "job_status": "QUEUED",
        "order_id": order.id
    }

@router.post("/release-code")
async def release_kiosk_print(
    req: ReleaseCodeRequest,
    db: Session = Depends(get_db)
):
    """
    Simulates Kiosk Touchscreen PIN verification:
    Validates single-use, non-expired PIN and dispatches document.
    """
    clean_code = req.release_code.replace("-", "").strip()
    code_hash = hash_token(clean_code)
    
    otp = db.query(OTP).filter(OTP.otp_hash == code_hash).first()
    if not otp:
        raise HTTPException(status_code=404, detail="Invalid 6-digit release PIN.")

    if not otp.active or otp.used_at is not None:
        raise HTTPException(status_code=400, detail="This release PIN has already been used.")

    # Check expiry
    now = datetime.now(timezone.utc)
    # Handle timezone-naive/aware comparisons safely
    otp_exp = otp.expires_at if otp.expires_at.tzinfo else otp.expires_at.replace(tzinfo=timezone.utc)
    if now > otp_exp:
        raise HTTPException(status_code=400, detail="This release PIN has expired. Please re-order.")

    # Mark OTP used
    otp.active = False
    otp.used_at = now

    # Transition PrintJob
    job = db.query(PrintJob).filter(PrintJob.order_id == otp.order_id).first()
    if job:
        job.status = PrintJobStatus.COMPLETED
        job.completed_at = now

    order = db.query(Order).filter(Order.id == otp.order_id).first()
    if order:
        order.status = OrderStatus.COMPLETED

    db.commit()

    return {
        "status": "COMPLETED",
        "message": "PIN verified! Document successfully released and printed at Kiosk Tray.",
        "order_id": otp.order_id
    }

@router.get("/status/{paypal_order_id}")
async def get_kiosk_job_status(
    paypal_order_id: str,
    db: Session = Depends(get_db)
):
    """Get status of an order and its kiosk print job."""
    payment = db.query(Payment).filter(Payment.razorpay_order_id == paypal_order_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Order not found.")

    order = db.query(Order).filter(Order.id == payment.order_id).first()
    job = db.query(PrintJob).filter(PrintJob.order_id == payment.order_id).first()
    otp = db.query(OTP).filter(OTP.order_id == payment.order_id).first()

    return {
        "order_id": order.id,
        "paypal_order_id": paypal_order_id,
        "status": order.status.value if order else "UNKNOWN",
        "amount": str(order.amount) if order else "0.00",
        "currency": order.currency if order else "USD",
        "job_status": job.status.value if job else "NONE",
        "release_code": otp.encrypted_value if otp and otp.active else None,
        "is_used": not otp.active if otp else False
    }

@router.get("/orders")
async def list_recent_orders(
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Lists recent kiosk orders for dashboard display."""
    orders = db.query(Order).order_by(Order.created_at.desc()).limit(limit).all()
    results = []
    for ord in orders:
        otp = db.query(OTP).filter(OTP.order_id == ord.id).first()
        results.append({
            "order_id": ord.id,
            "status": ord.status.value,
            "pages": ord.total_pages,
            "amount": str(ord.amount),
            "currency": ord.currency,
            "filename": ord.print_settings.get("filename", "document.pdf") if ord.print_settings else "document.pdf",
            "mode": ord.print_settings.get("mode", "summary") if ord.print_settings else "summary",
            "release_code": otp.encrypted_value if otp else None,
            "created_at": ord.created_at.isoformat() if ord.created_at else None
        })
    return {"orders": results}

@router.delete("/orders/{order_id}")
async def cancel_kiosk_order(
    order_id: str,
    db: Session = Depends(get_db)
):
    """Cancels an order and deactivates associated release code."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    otp = db.query(OTP).filter(OTP.order_id == order.id).first()
    if otp:
        otp.active = False

    job = db.query(PrintJob).filter(PrintJob.order_id == order.id).first()
    if job:
        job.status = PrintJobStatus.CANCELLED

    order.status = OrderStatus.CANCELLED
    db.commit()

    return {"status": "CANCELLED", "order_id": order_id, "message": "Order cancelled."}

@router.get("/stats")
async def get_kiosk_system_stats(
    db: Session = Depends(get_db)
):
    """Returns kiosk station overview and hardware status."""
    station = _get_or_create_default_station(db)
    printers = db.query(Printer).filter(Printer.server_id == station.id).all()
    total_orders = db.query(Order).count()
    completed_orders = db.query(Order).filter(Order.status == OrderStatus.COMPLETED).count()
    paid_orders = db.query(Order).filter(Order.status == OrderStatus.PAID).count()

    return {
        "station_id": station.id,
        "station_name": station.name,
        "station_location": station.location,
        "station_status": station.status.value,
        "total_orders": total_orders,
        "completed_orders": completed_orders,
        "active_jobs": paid_orders,
        "printers": [
            {
                "id": p.id,
                "name": p.display_name or p.cups_printer_name,
                "status": p.printer_status,
                "supports_color": p.supports_color,
                "supports_duplex": p.supports_duplex
            }
            for p in printers
        ]
    }

