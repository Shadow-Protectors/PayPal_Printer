from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from app.db.models.payment import PaymentStatus

class PaymentCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    orderId: str = Field(..., alias="orderId")

    def __init__(self, **data):
        if "order_id" in data and "orderId" not in data:
            data["orderId"] = data.pop("order_id")
        super().__init__(**data)

class PaymentCreateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    paymentId: str = Field(..., alias="paymentId", serialization_alias="paymentId")
    orderId: str = Field(..., alias="orderId", serialization_alias="orderId")
    razorpayOrderId: str = Field(..., alias="razorpayOrderId", serialization_alias="razorpayOrderId")
    amount: float
    amountPaise: int = Field(..., alias="amountPaise", serialization_alias="amountPaise")
    currency: str
    keyId: str = Field(..., alias="keyId", serialization_alias="keyId")

    def __init__(self, **data):
        if "payment_id" in data and "paymentId" not in data:
            data["paymentId"] = data.pop("payment_id")
        if "order_id" in data and "orderId" not in data:
            data["orderId"] = data.pop("order_id")
        if "razorpay_order_id" in data and "razorpayOrderId" not in data:
            data["razorpayOrderId"] = data.pop("razorpay_order_id")
        if "amount_paise" in data and "amountPaise" not in data:
            data["amountPaise"] = data.pop("amount_paise")
        if "key_id" in data and "keyId" not in data:
            data["keyId"] = data.pop("key_id")
        super().__init__(**data)

class PaymentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: str
    orderId: str = Field(..., alias="orderId", serialization_alias="orderId")
    razorpayOrderId: str = Field(..., alias="razorpayOrderId", serialization_alias="razorpayOrderId")
    razorpayPaymentId: Optional[str] = Field(default=None, alias="razorpayPaymentId", serialization_alias="razorpayPaymentId")
    amount: float
    currency: str
    status: PaymentStatus
    createdAt: datetime = Field(..., alias="createdAt", serialization_alias="createdAt")

class PaymentVerifyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    orderId: str = Field(..., alias="orderId")
    razorpayOrderId: Optional[str] = Field(default=None, alias="razorpayOrderId")
    razorpayPaymentId: Optional[str] = Field(default=None, alias="razorpayPaymentId")
    razorpaySignature: Optional[str] = Field(default=None, alias="razorpaySignature")

    def __init__(self, **data):
        if "order_id" in data and "orderId" not in data:
            data["orderId"] = data.pop("order_id")
        if "razorpay_order_id" in data and "razorpayOrderId" not in data:
            data["razorpayOrderId"] = data.pop("razorpay_order_id")
        if "razorpay_payment_id" in data and "razorpayPaymentId" not in data:
            data["razorpayPaymentId"] = data.pop("razorpay_payment_id")
        if "razorpay_signature" in data and "razorpaySignature" not in data:
            data["razorpaySignature"] = data.pop("razorpay_signature")
        super().__init__(**data)
