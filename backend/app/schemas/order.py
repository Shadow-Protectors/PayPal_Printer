from datetime import datetime, timezone
from typing import Literal, Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator, field_serializer
from app.db.models.order import OrderStatus

class PrintSettingsSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    copies: int = Field(default=1, ge=1, le=100)
    pageRange: Optional[str] = Field(default=None, alias="pageRange", serialization_alias="pageRange", max_length=2048)
    colour: bool = Field(default=False)
    sides: Literal["one-sided", "two-sided-long-edge", "two-sided-short-edge"] = Field(default="one-sided")
    paperSize: Literal["A4", "Letter", "Legal"] = Field(default="A4", alias="paperSize", serialization_alias="paperSize")
    orientation: Literal["portrait", "landscape"] = Field(default="portrait")

    @model_validator(mode="before")
    @classmethod
    def normalize_settings(cls, data: Any):
        if not isinstance(data, dict):
            return data
        if "page_range" in data and "pageRange" not in data:
            data["pageRange"] = data.pop("page_range")
        if "paper_size" in data and "paperSize" not in data:
            data["paperSize"] = data.pop("paper_size")
        if "colorMode" in data and "colour" not in data:
            data["colour"] = (str(data.pop("colorMode")).upper() == "COLOR")
        if "color_mode" in data and "colour" not in data:
            data["colour"] = (str(data.pop("color_mode")).upper() == "COLOR")
        if "duplex" in data and "sides" not in data:
            data["sides"] = "two-sided-long-edge" if data.pop("duplex") else "one-sided"
        return data

class OrderItemConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    documentId: str = Field(..., alias="documentId")
    settings: PrintSettingsSchema = Field(default_factory=PrintSettingsSchema)

    @model_validator(mode="before")
    @classmethod
    def normalize_item(cls, data: Any):
        if not isinstance(data, dict):
            return data
        if "document_id" in data and "documentId" not in data:
            data["documentId"] = data.pop("document_id")
        if "settings" in data and isinstance(data["settings"], (PrintSettingsSchema, dict)):
            return data
        settings_dict = {}
        for k in ["copies", "pageRange", "page_range", "colour", "colorMode", "color_mode", "sides", "duplex", "paperSize", "paper_size", "orientation"]:
            if k in data:
                settings_dict[k] = data[k]
        data["settings"] = settings_dict
        return data

class OrderCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    documentId: Optional[str] = Field(default=None, alias="documentId")
    printServerId: str = Field(..., alias="printServerId")
    rollNumber: Optional[str] = Field(default=None, alias="rollNumber")
    department: Optional[str] = Field(default=None, alias="department")
    email: Optional[str] = Field(default=None, alias="email")
    settings: Optional[PrintSettingsSchema] = None
    items: Optional[List[OrderItemConfig]] = Field(default=None, max_length=10)

    @model_validator(mode="before")
    @classmethod
    def normalize_input(cls, data: Any):
        if not isinstance(data, dict):
            return data
        if "document_id" in data and "documentId" not in data:
            data["documentId"] = data.pop("document_id")
        if "print_server_id" in data and "printServerId" not in data:
            data["printServerId"] = data.pop("print_server_id")
        if "roll_number" in data and "rollNumber" not in data:
            data["rollNumber"] = data.pop("roll_number")

        if "items" in data and isinstance(data["items"], list) and len(data["items"]) > 0:
            if not data.get("documentId"):
                first_item = data["items"][0]
                data["documentId"] = first_item.get("documentId") or first_item.get("document_id")
        
        # If settings is missing, automatically construct it from top-level fields
        if "settings" not in data or (not isinstance(data["settings"], dict) and not isinstance(data["settings"], PrintSettingsSchema)):
            settings_dict = {}
            for k in ["copies", "pageRange", "page_range", "colour", "colorMode", "color_mode", "sides", "duplex", "paperSize", "paper_size", "orientation"]:
                if k in data:
                    settings_dict[k] = data[k]
            data["settings"] = settings_dict
        return data

import copy

def sanitize_print_settings(settings: Any) -> Dict[str, Any]:
    """
    Strips plaintext OTP values from printer_otps structure while preserving
    otp_hash, active state, cups_printer_name, and other configuration fields.
    """
    if not settings or not isinstance(settings, dict):
        return {}
    clean = copy.deepcopy(settings)
    clean.pop("session_token", None)
    if "printer_otps" in clean and isinstance(clean["printer_otps"], dict):
        for _, p_val in clean["printer_otps"].items():
            if isinstance(p_val, dict):
                p_val.pop("otp", None)
                p_val.pop("otp_hash", None)
    return clean

class OrderResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: str
    userId: Optional[int] = Field(default=None, alias="userId", serialization_alias="userId")
    rollNumber: Optional[str] = Field(default=None, alias="rollNumber", serialization_alias="rollNumber")
    department: Optional[str] = Field(default=None, alias="department", serialization_alias="department")
    documentId: str = Field(..., alias="documentId", serialization_alias="documentId")
    printServerId: str = Field(..., alias="printServerId", serialization_alias="printServerId")
    printSettings: Dict[str, Any] = Field(..., alias="printSettings", serialization_alias="printSettings")
    totalPages: int = Field(..., alias="totalPages", serialization_alias="totalPages")
    copies: int
    amount: float
    currency: str
    status: OrderStatus
    releaseCode: Optional[str] = Field(default=None, alias="releaseCode", serialization_alias="releaseCode")
    errorCode: Optional[str] = Field(default=None, alias="errorCode", serialization_alias="errorCode")
    errorMessage: Optional[str] = Field(default=None, alias="errorMessage", serialization_alias="errorMessage")
    createdAt: datetime = Field(..., alias="createdAt", serialization_alias="createdAt")

    @field_serializer("createdAt")
    def serialize_created_at(self, dt: datetime, _info):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    @field_validator("printSettings", mode="before")
    @classmethod
    def strip_plaintext_otp_validator(cls, v: Any) -> Dict[str, Any]:
        return sanitize_print_settings(v)

    def __init__(self, **data):
        if "user_id" in data and "userId" not in data:
            data["userId"] = data.pop("user_id")
        if "roll_number" in data and "rollNumber" not in data:
            data["rollNumber"] = data.pop("roll_number")
        if "document_id" in data and "documentId" not in data:
            data["documentId"] = data.pop("document_id")
        if "print_server_id" in data and "printServerId" not in data:
            data["printServerId"] = data.pop("print_server_id")
        if "print_settings" in data and "printSettings" not in data:
            data["printSettings"] = data.pop("print_settings")
        if "printSettings" in data:
            data["printSettings"] = sanitize_print_settings(data["printSettings"])
        if "total_pages" in data and "totalPages" not in data:
            data["totalPages"] = data.pop("total_pages")
        if "release_code" in data and "releaseCode" not in data:
            data["releaseCode"] = data.pop("release_code")
        if "error_code" in data and "errorCode" not in data:
            data["errorCode"] = data.pop("error_code")
        if "error_message" in data and "errorMessage" not in data:
            data["errorMessage"] = data.pop("error_message")
        if "created_at" in data and "createdAt" not in data:
            data["createdAt"] = data.pop("created_at")
        super().__init__(**data)

class OTPResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    orderId: str = Field(..., alias="orderId", serialization_alias="orderId")
    otp: str
    expiresAt: Optional[datetime] = Field(default=None, alias="expiresAt", serialization_alias="expiresAt")
    printerOtps: Optional[Dict[str, Any]] = Field(default=None, alias="printerOtps", serialization_alias="printerOtps")
    selectedPrinter: Optional[str] = Field(default=None, alias="selectedPrinter", serialization_alias="selectedPrinter")
    printerSelectionLocked: Optional[bool] = Field(default=False, alias="printerSelectionLocked", serialization_alias="printerSelectionLocked")

    def __init__(self, **data):
        if "order_id" in data and "orderId" not in data:
            data["orderId"] = data.pop("order_id")
        if "expires_at" in data and "expiresAt" not in data:
            data["expiresAt"] = data.pop("expires_at")
        if "printer_otps" in data and "printerOtps" not in data:
            data["printerOtps"] = data.pop("printer_otps")
        if "selected_printer" in data and "selectedPrinter" not in data:
            data["selectedPrinter"] = data.pop("selected_printer")
        if "printer_selection_locked" in data and "printerSelectionLocked" not in data:
            data["printerSelectionLocked"] = data.pop("printer_selection_locked")
        super().__init__(**data)
