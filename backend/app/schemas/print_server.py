from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from app.db.models.print_server import PrintServerStatus

class PrinterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    server_id: str
    cups_printer_name: str
    display_name: str
    model: Optional[str] = None
    location: Optional[str] = None
    department_id: Optional[int] = None
    printer_status: Optional[str] = "READY"
    supports_color: bool = True
    supports_duplex: bool = True
    is_active: bool = True
    is_enabled: bool = True

class PrintServerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    location: Optional[str] = None
    department_id: Optional[int] = None
    status: PrintServerStatus
    last_heartbeat: Optional[datetime] = None
    printer_state: Optional[str] = None
    paper_state: Optional[str] = None
    software_version: Optional[str] = None
    printers: List[PrinterResponse] = []

class ReportedPrinterInfo(BaseModel):
    cups_printer_name: str
    ip_address: Optional[str] = None
    device_uri: Optional[str] = None
    status: Optional[str] = "READY"
    jobs: Optional[int] = 0
    supports_color: Optional[bool] = None
    supports_duplex: Optional[bool] = None

    def __init__(self, **data):
        if "cups_name" in data and "cups_printer_name" not in data:
            data["cups_printer_name"] = data.pop("cups_name")
        if "name" in data and "cups_printer_name" not in data:
            data["cups_printer_name"] = data.pop("name")
        super().__init__(**data)

class HeartbeatRequest(BaseModel):
    printerState: str = "READY"
    paperState: str = "AVAILABLE"
    printers: Optional[List[ReportedPrinterInfo]] = None
    version: Optional[str] = None
    timestamp: Optional[datetime] = None

    def __init__(self, **data):
        if "printer_state" in data and "printerState" not in data:
            data["printerState"] = data.pop("printer_state")
        if "paper_state" in data and "paperState" not in data:
            data["paperState"] = data.pop("paper_state")
        if "software_version" in data and "version" not in data:
            data["version"] = data.pop("software_version")
        super().__init__(**data)

class HeartbeatResponse(BaseModel):
    status: str
    server_time: datetime
    assignments: List[dict] = []
