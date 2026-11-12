from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Kiosk"])


@router.get("/kiosk", response_class=HTMLResponse)
def kiosk_information():
    return HTMLResponse("""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Print station</title></head><body><h1>Use the department touchscreen</h1><p>Enter your release code at the physical print station. The Raspberry Pi serves its keypad at its local /kiosk address.</p><p><a href="/">Open customer website</a></p></body></html>""", status_code=410)
