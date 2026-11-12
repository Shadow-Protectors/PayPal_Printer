from fastapi import APIRouter, Depends, Request, Header, status
from sqlalchemy.orm import Session
from typing import Optional

from app.db.session import get_db
from app.schemas.payment import PaymentCreateRequest, PaymentCreateResponse, PaymentVerifyRequest
from app.services.payment_service import payment_service
from app.api.customer_access import customer_access

router = APIRouter(prefix="/api/payments", tags=["Payments"])

@router.get("/capabilities")
def payment_capabilities():
    from app.config.settings import settings
    return {"paymentMode": "test" if settings.RAZORPAY_KEY_ID.startswith("rzp_test_") else "live"}

@router.post("/create", dependencies=[Depends(customer_access)], response_model=PaymentCreateResponse, status_code=status.HTTP_201_CREATED)
def create_payment(
    req: PaymentCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Public payment initiation - no login required.
    Initializes a Razorpay order for the requested print order.
    """
    print(f"\n[BACKEND_PAYMENT] >>> Creating payment for order: {req.orderId}")
    res = payment_service.create_payment(
        db=db,
        order_id=req.orderId,
        user_id=None
    )
    print(f"[BACKEND_PAYMENT] <<< Payment Order Ready: keyId={res.keyId}, razorpayOrderId={res.razorpayOrderId}, amountPaise={res.amountPaise}")
    return res

@router.post("/verify", dependencies=[Depends(customer_access)])
def verify_payment(
    req: PaymentVerifyRequest,
    db: Session = Depends(get_db)
):
    """
    Verifies / confirms payment and transitions order to WAITING_FOR_OTP,
    automatically generating the 6-digit release OTP.
    """
    print(f"\n[BACKEND_PAYMENT] >>> Verifying payment: orderId={req.orderId}, rzpPaymentId={req.razorpayPaymentId}, rzpOrderId={req.razorpayOrderId}")
    res = payment_service.verify_or_confirm_payment(
        db=db,
        order_id=req.orderId,
        rzp_order_id=req.razorpayOrderId,
        rzp_payment_id=req.razorpayPaymentId,
        rzp_signature=req.razorpaySignature
    )
    print(f"[BACKEND_PAYMENT] <<< Payment verification complete for {req.orderId}: status={res.get('status')}")
    return res

@router.post("/reconcile", dependencies=[Depends(customer_access)])
def reconcile_payment(
    payload: dict,
    db: Session = Depends(get_db)
):
    """
    Reconciles payment status for an order.
    Checks if order or payment record is confirmed and idempotently updates state.
    """
    from app.utils.errors import AppException

    order_id = payload.get("orderId") or payload.get("order_id")
    if not order_id:
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="MISSING_ORDER_ID",
            message="orderId is required."
        )

    return payment_service.reconcile_payment(db, order_id)

@router.post("/webhook")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature"),
    db: Session = Depends(get_db)
):
    raw_body = await request.body()
    result = payment_service.handle_webhook(
        db=db,
        raw_body=raw_body,
        signature=x_razorpay_signature
    )
    return result
