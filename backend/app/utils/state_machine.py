from typing import Set, Dict
from app.db.models.order import OrderStatus
from app.db.models.print_job import PrintJobStatus
from app.db.models.refund import RefundStatus
from app.utils.errors import AppException
from fastapi import status

# Order state allowed transitions
ORDER_STATE_TRANSITIONS: Dict[OrderStatus, Set[OrderStatus]] = {
    OrderStatus.CREATED: {OrderStatus.PAID, OrderStatus.CANCELLED, OrderStatus.FAILED, OrderStatus.EXPIRED},
    OrderStatus.PAID: {OrderStatus.JOB_QUEUED, OrderStatus.WAITING_FOR_OTP, OrderStatus.CANCELLED, OrderStatus.FAILED},
    OrderStatus.JOB_QUEUED: {OrderStatus.WAITING_FOR_OTP, OrderStatus.CANCELLED, OrderStatus.FAILED},
    OrderStatus.WAITING_FOR_OTP: {OrderStatus.RELEASED, OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.FAILED},
    OrderStatus.RELEASED: {OrderStatus.PRINTING, OrderStatus.COMPLETED, OrderStatus.FAILED},
    OrderStatus.PRINTING: {OrderStatus.COMPLETED, OrderStatus.FAILED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: {OrderStatus.REFUNDED, OrderStatus.WAITING_FOR_OTP},
    OrderStatus.FAILED: {OrderStatus.REFUNDED, OrderStatus.WAITING_FOR_OTP},
    OrderStatus.EXPIRED: {OrderStatus.REFUNDED},
    OrderStatus.REFUNDED: set(),
}

# Print Job state allowed transitions
JOB_STATE_TRANSITIONS: Dict[PrintJobStatus, Set[PrintJobStatus]] = {
    PrintJobStatus.QUEUED: {PrintJobStatus.RELEASED, PrintJobStatus.CANCELLED, PrintJobStatus.FAILED, PrintJobStatus.FINAL_FAILED},
    PrintJobStatus.RELEASED: {PrintJobStatus.PRINTING, PrintJobStatus.COMPLETED, PrintJobStatus.FAILED, PrintJobStatus.FINAL_FAILED},
    PrintJobStatus.PRINTING: {PrintJobStatus.COMPLETED, PrintJobStatus.FAILED, PrintJobStatus.FINAL_FAILED},
    PrintJobStatus.FAILED: {PrintJobStatus.QUEUED, PrintJobStatus.FINAL_FAILED},
    PrintJobStatus.CANCELLED: {PrintJobStatus.QUEUED},
    PrintJobStatus.COMPLETED: set(),
    PrintJobStatus.FINAL_FAILED: {PrintJobStatus.QUEUED},
}

# Refund state allowed transitions
REFUND_STATE_TRANSITIONS: Dict[RefundStatus, Set[RefundStatus]] = {
    RefundStatus.NOT_REQUIRED: {RefundStatus.PENDING},
    RefundStatus.PENDING: {RefundStatus.PROCESSING, RefundStatus.FAILED, RefundStatus.NOT_REQUIRED},
    RefundStatus.PROCESSING: {RefundStatus.COMPLETED, RefundStatus.FAILED},
    RefundStatus.FAILED: {RefundStatus.PENDING},
    RefundStatus.COMPLETED: set(),
}

def validate_order_transition(current: OrderStatus, target: OrderStatus):
    if current == target:
        return
    allowed = ORDER_STATE_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_STATE",
            message=f"Illegal order state transition from {current.value} to {target.value}."
        )

def validate_job_transition(current: PrintJobStatus, target: PrintJobStatus):
    if current == target:
        return
    allowed = JOB_STATE_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_STATE",
            message=f"Illegal print job state transition from {current.value} to {target.value}."
        )

def validate_refund_transition(current: RefundStatus, target: RefundStatus):
    allowed = REFUND_STATE_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_STATE",
            message=f"Illegal refund state transition from {current.value} to {target.value}."
        )
