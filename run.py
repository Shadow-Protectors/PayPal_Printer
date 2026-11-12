import sys
from pathlib import Path
import uvicorn

# Ensure backend directory is in python path
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

if __name__ == "__main__":
    print("=" * 60)
    print(" SmartPrint AI - Autonomous Campus Print Kiosk (PayPal)")
    print(" Web UI & API running at: http://127.0.0.1:8000")
    print("=" * 60)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True, app_dir=str(backend_dir))
