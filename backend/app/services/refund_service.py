import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from fastapi import status

from app.config.settings import settings
from app.db.models.order import Order, OrderStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.refund import Refund, RefundStatus
from app.utils.errors import AppException
from app.utils.state_machine import validate_order_transition, validate_refund_transition

class RefundService:
    @staticmethod
    def reconcile_pending(db):
        from app.services.payment_service import payment_service
        pending = db.query(Refund).filter(Refund.status == RefundStatus.PROCESSING,
                                         Refund.razorpay_refund_id != None).all()
        if not pending:
            return
        gateway = payment_service._gateway_client()
        for refund in pending:
            entity = payment_service._gateway_call(gateway.refund.fetch, refund.razorpay_refund_id)
            payment = db.get(Payment, refund.payment_id)
            if (entity.get("id") != refund.razorpay_refund_id or
                    entity.get("payment_id") != payment.razorpay_payment_id or
                    entity.get("amount") != int(Decimal(str(refund.amount)) * 100)):
                raise AppException(409, "REFUND_REVIEW_REQUIRED", "Gateway refund does not match the recorded payment.")
            if entity.get("status") == "processed":
                refund.status = RefundStatus.COMPLETED
                refund.refund_completed_at = datetime.now(timezone.utc)
                payment.status = PaymentStatus.REFUNDED
                order = db.get(Order, refund.order_id)
                if order.status in (OrderStatus.CANCELLED, OrderStatus.FAILED, OrderStatus.EXPIRED):
                    order.status = OrderStatus.REFUNDED
            elif entity.get("status") == "failed":
                refund.status = RefundStatus.FAILED
                refund.error_message = "Gateway reports refund failed. Manual review required."
            db.commit()

    @staticmethod
    def process_refund(db: Session, order_id: str, reason: str = "Print failed") -> Refund:
        # Callers can mark a job/order failed in this same transaction with
        # autoflush disabled. Persist those changes before refreshing locks.
        db.flush()
        order = db.query(Order).filter(Order.id == order_id).with_for_update().populate_existing().first()
        if not order:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="NOT_FOUND",
                message="Order not found for refund."
            )

        # Serialize against admin retry before checking refund/payment state.
        existing = db.query(Refund).filter(Refund.order_id == order_id).with_for_update().populate_existing().first()
        if existing and existing.status in (RefundStatus.COMPLETED, RefundStatus.PROCESSING):
            return existing
        if order.status not in (OrderStatus.FAILED, OrderStatus.CANCELLED, OrderStatus.EXPIRED):
            raise AppException(409, "REFUND_NOT_ELIGIBLE", "This order is not eligible for a refund.")

        payment = db.query(Payment).filter(Payment.order_id == order_id).first()
        if not payment or payment.status != PaymentStatus.CAPTURED:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="REFUND_NOT_ELIGIBLE",
                message="Payment is not captured or does not exist for this order."
            )

        if not existing:
            refund_id = f"ref_{uuid.uuid4().hex[:12]}"
            refund = Refund(
                id=refund_id,
                order_id=order.id,
                payment_id=payment.id,
                amount=order.amount,
                reason=reason,
                status=RefundStatus.PENDING,
                refund_requested_at=datetime.now(timezone.utc)
            )
            db.add(refund)
            db.flush()
        else:
            refund = existing
            if refund.status == RefundStatus.NOT_REQUIRED:
                # An approved retry cancelled an unsubmitted refund. A later
                # confirmed print failure can create a fresh refund attempt.
                validate_refund_transition(refund.status, RefundStatus.PENDING)
                refund.status = RefundStatus.PENDING
                refund.reason = reason

        # Process with Razorpay if payment_id exists
        if refund.status == RefundStatus.FAILED:
            raise AppException(409, "REFUND_REVIEW_REQUIRED", "Check the gateway for an existing refund before retrying.")
        validate_refund_transition(refund.status, RefundStatus.PROCESSING)
        refund.status = RefundStatus.PROCESSING
        # Persist the attempt before gateway I/O. After a crash the outcome needs
        # review rather than issuing a second refund for the same payment.
        db.commit()

        # Test gateway payments also require a real gateway refund response.
        # Never invent a successful refund after a network error.
        if not payment.razorpay_payment_id:
            refund.status = RefundStatus.FAILED
            refund.error_message = "Captured payment has no gateway payment ID. Manual review required."
            db.commit()
            raise AppException(409, "REFUND_REVIEW_REQUIRED", refund.error_message)
        try:
            from app.services.payment_service import payment_service
            gateway = payment_service._gateway_client()
            response = payment_service._gateway_call(gateway.payment.refund, payment.razorpay_payment_id, {
                "amount": int(Decimal(str(refund.amount)) * 100),
                "notes": {"reason": reason, "orderId": order.id},
            })
            rzp_refund_id = response.get("id")
            if not rzp_refund_id or response.get("status") not in ("processed", "pending"):
                raise ValueError("Gateway refund response is incomplete")
            refund.razorpay_refund_id = rzp_refund_id
            if response["status"] == "pending":
                db.commit()
                db.refresh(refund)
                return refund
        except Exception as exc:
            refund.status = RefundStatus.FAILED
            refund.error_message = "Gateway refund outcome needs review. Check Razorpay before retrying."
            db.commit()
            raise AppException(502, "REFUND_FAILED", refund.error_message) from exc

        success = True
        if success:
            validate_refund_transition(refund.status, RefundStatus.COMPLETED)
            refund.status = RefundStatus.COMPLETED
            refund.razorpay_refund_id = rzp_refund_id
            refund.refund_completed_at = datetime.now(timezone.utc)

            payment.status = PaymentStatus.REFUNDED
            if order.status in [OrderStatus.FAILED, OrderStatus.EXPIRED, OrderStatus.CANCELLED]:
                validate_order_transition(order.status, OrderStatus.REFUNDED)
                order.status = OrderStatus.REFUNDED

            db.commit()
            db.refresh(refund)
            try:
                from app.services.email_service import email_service
                email_service.notify_order_status(
                    db, order, OrderStatus.REFUNDED,
                    extra_info={"refund_status": "COMPLETED", "error_message": reason}
                )
            except Exception:
                pass

        return refund

refund_service = RefundService()
