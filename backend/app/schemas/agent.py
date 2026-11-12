from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from app.db.models.print_job import PrintJobStatus

class AgentJobResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jobId: str = Field(..., alias="jobId", serialization_alias="jobId")
    orderId: str = Field(..., alias="orderId", serialization_alias="orderId")
    storageKey: str = Field(..., alias="storageKey", serialization_alias="storageKey")
    settings: Dict[str, Any]

    def __init__(self, **data):
        if "job_id" in data and "jobId" not in data:
            data["jobId"] = data.pop("job_id")
        if "order_id" in data and "orderId" not in data:
            data["orderId"] = data.pop("order_id")
        if "storage_key" in data and "storageKey" not in data:
            data["storageKey"] = data.pop("storage_key")
        super().__init__(**data)

class AgentReleaseRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    otp: str

class AgentReleaseResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    jobId: str = Field(..., alias="jobId", serialization_alias="jobId")
    orderId: str = Field(..., alias="orderId", serialization_alias="orderId")
    status: PrintJobStatus
    storageKey: str = Field(..., alias="storageKey", serialization_alias="storageKey")
    settings: Dict[str, Any]

    def __init__(self, **data):
        if "job_id" in data and "jobId" not in data:
            data["jobId"] = data.pop("job_id")
        if "order_id" in data and "orderId" not in data:
            data["orderId"] = data.pop("order_id")
        if "storage_key" in data and "storageKey" not in data:
            data["storageKey"] = data.pop("storage_key")
        super().__init__(**data)

class AgentJobStatusUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: PrintJobStatus
    cupsJobId: Optional[str] = Field(default=None, alias="cupsJobId", serialization_alias="cupsJobId")
    errorCode: Optional[str] = Field(default=None, alias="errorCode", serialization_alias="errorCode")
    message: Optional[str] = None
    eventId: Optional[str] = Field(default=None, max_length=64)

    def __init__(self, **data):
        if "cups_job_id" in data and "cupsJobId" not in data:
            data["cupsJobId"] = data.pop("cups_job_id")
        if "error_code" in data and "errorCode" not in data:
            data["errorCode"] = data.pop("error_code")
        super().__init__(**data)
