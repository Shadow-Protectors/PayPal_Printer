import os
import sys
import mimetypes
from pathlib import Path
from contextlib import asynccontextmanager

mimetypes.add_type("application/javascript", ".mjs")

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config.settings import settings
from app.config.database import engine
from app.db.base import Base
from app.services.storage_service import storage_service
from app.utils.errors import (
    AppException,
    app_exception_handler,
    validation_exception_handler,
    general_exception_handler,
)

from app.api.routes.auth import router as auth_router
from app.api.routes.documents import router as documents_router
from app.api.routes.print_servers import router as print_servers_router
from app.api.routes.orders import router as orders_router
from app.api.routes.payments import router as payments_router
from app.api.routes.agent import router as agent_router
from app.api.routes.maintenance import router as maintenance_router
from app.api.routes.kiosk import router as kiosk_router
from app.api.routes.sessions import router as sessions_router
from app.api.routes.admin import router as admin_router
from app.api.routes.departments import router as departments_router
from app.api.routes.reports import router as reports_router
from app.api.routes.paypal_kiosk import router as paypal_kiosk_router

def _sync_missing_columns():
    from app.db.migrate import sync_schema
    sync_schema(engine)

def _ensure_admin_user():
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        return
    from app.config.database import SessionLocal
    from app.db.models.user import User, UserRole
    from app.config.security import hash_password, verify_password
    import logging
    logger = logging.getLogger("uvicorn.error")
    db = SessionLocal()
    try:
        admin_email = settings.ADMIN_EMAIL.strip().lower()
        admin = db.query(User).filter(User.email == admin_email).first()
        if not admin:
            admin = User(
                email=admin_email,
                full_name=settings.ADMIN_NAME or "Platform Administrator",
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True
            )
            db.add(admin)
            db.commit()
            logger.info("Initialized administrator account from environment: %s", admin_email)
        else:
            changed = False
            if admin.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
                raise RuntimeError('Configured administrator email belongs to a customer. Resolve it with the explicit admin seed command.')
            if not admin.is_active:
                admin.is_active = True
                changed = True
            if not admin.password_hash or not verify_password(settings.ADMIN_PASSWORD, admin.password_hash):
                admin.password_hash = hash_password(settings.ADMIN_PASSWORD)
                changed = True
            if changed:
                db.commit()
                logger.info("Synchronized administrator credentials from environment: %s", admin_email)
    except Exception as e:
        logger.warning("Could not auto-sync admin user: %s", e)
        raise
    finally:
        db.close()


def _ensure_default_station():
    from app.config.database import SessionLocal
    from app.db.models.print_server import PrintServer, PrintServerStatus
    from app.db.models.printer import Printer
    from app.config.security import hash_token
    import logging
    from datetime import datetime, timezone
    logger = logging.getLogger("uvicorn.error")
    db = SessionLocal()
    try:
        station_id = (getattr(settings, 'DEFAULT_PRINT_SERVER_ID', '') or "PRINT-SERVER-001").strip()
        raw_token = (getattr(settings, 'INTERNAL_AGENT_TOKEN', '') or "default_internal_agent_token").strip()
        token_hash = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        
        server = db.query(PrintServer).filter(PrintServer.id == station_id).first()
        if not server:
            server = PrintServer(
                id=station_id,
                name=getattr(settings, 'DEFAULT_PRINT_SERVER_NAME', None) or "Central Library Station",
                location=getattr(settings, 'DEFAULT_PRINT_SERVER_LOCATION', None) or "Main Campus Library Floor 1",
                device_token_hash=token_hash,
                status=PrintServerStatus.ONLINE,
                is_enabled=True,
                last_heartbeat=now,
                last_seen=now,
                printer_state="READY",
                paper_state="AVAILABLE",
            )
            db.add(server)
            db.commit()
            logger.info("Initialized default print server station: %s", station_id)
        else:
            server.status = PrintServerStatus.ONLINE
            server.is_enabled = True
            server.last_heartbeat = now
            server.last_seen = now
            server.printer_state = "READY"
            server.paper_state = "AVAILABLE"
            db.commit()

        # Also ensure at least one active printer exists for this station
        printer = db.query(Printer).filter(Printer.id == "printer_01").first()
        if not printer:
            printer = Printer(
                id="printer_01",
                server_id=station_id,
                cups_printer_name="campus_laser_01",
                display_name="Main Campus High-Speed Laser",
                supports_color=True,
                supports_duplex=True,
                is_enabled=True,
                is_active=True,
                printer_status="READY",
                last_seen=now,
                has_mismatch=False,
            )
            db.add(printer)
            db.commit()
            logger.info("Initialized default printer for station: %s", station_id)
        else:
            printer.server_id = station_id
            printer.is_enabled = True
            printer.is_active = True
            printer.printer_status = "READY"
            printer.last_seen = now
            printer.has_mismatch = False
            db.commit()
            printer.is_enabled = True
            printer.is_active = True
            printer.printer_status = "READY"
            printer.last_seen = now
            printer.has_mismatch = False
            db.commit()
    except Exception as e:
        logger.warning("Could not auto-sync default print server: %s", e)
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables and storage dirs exist
    Base.metadata.create_all(bind=engine)
    _sync_missing_columns()
    _ensure_admin_user()
    _ensure_default_station()
    storage_service._ensure_directories()
    yield
    # Shutdown

is_production = settings.ENVIRONMENT.lower() in ("production", "prod")

app = FastAPI(
    title=settings.APP_NAME,
    description="Smart Self-Service Printing Platform FastAPI Backend",
    version="1.0.0",
    root_path=settings.ROOT_PATH,
    lifespan=lifespan,
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    openapi_url=None if is_production else "/openapi.json",
)

# CORS configuration: production accepts only configured origins.
cors_origins = settings.ALLOWED_ORIGINS if isinstance(settings.ALLOWED_ORIGINS, list) else [settings.ALLOWED_ORIGINS]


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


import time

@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    from fastapi.responses import JSONResponse
    maximum = (settings.MAX_UPLOAD_MB + 1) * 1024 * 1024
    length = request.headers.get('content-length')
    if length:
        try:
            if int(length) < 0 or int(length) > maximum:
                return JSONResponse(status_code=413, content={'error': 'REQUEST_TOO_LARGE', 'message': 'Request exceeds upload limit.'})
        except ValueError:
            return JSONResponse(status_code=400, content={'error': 'INVALID_CONTENT_LENGTH'})
    start = time.time()
    method = request.method
    path = request.url.path
    print(f"[BACKEND_LOG] >>> {method} {path}")
    try:
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        duration_ms = (time.time() - start) * 1000
        print(f"[BACKEND_LOG] <<< {method} {path} - Status: {response.status_code} ({duration_ms:.1f}ms)")
        if path == "/" or path.endswith(".html") or path.endswith(".js") or "flutter" in path:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response
    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        print(f"[BACKEND_LOG] !!! {method} {path} - Error: {e} ({duration_ms:.1f}ms)")
        raise

# Exception handlers
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Routers
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(print_servers_router)
app.include_router(orders_router)
app.include_router(payments_router)
app.include_router(agent_router)
app.include_router(maintenance_router)
app.include_router(kiosk_router)
app.include_router(sessions_router)
app.include_router(admin_router)
app.include_router(departments_router)
app.include_router(reports_router)
app.include_router(paypal_kiosk_router)

from app.schemas.agent import AgentReleaseRequest
from app.db.session import get_db
from sqlalchemy.orm import Session
from fastapi import Depends

@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT
    }

@app.get("/local/status", include_in_schema=False)
@app.post("/local/release", include_in_schema=False)
@app.get("/local/job-status/{job_id}", include_in_schema=False)
def retired_hardware_proxy(job_id: str = ""):
    return JSONResponse(status_code=410, content={"error": "STATION_RELEASE_REQUIRED",
        "message": "Use the physical station touchscreen. Customer status is available through the order API."})

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# APK download routes
downloads_dir = Path(__file__).resolve().parent.parent.parent / "downloads"

@app.get("/api/downloads/apk", tags=["Downloads"], operation_id="download_apk_api")
def download_achuppori_apk():
    apk_file = downloads_dir / "achuppori.apk"
    if apk_file.exists():
        return FileResponse(
            path=str(apk_file),
            filename="achuppori.apk",
            media_type="application/vnd.android.package-archive"
        )
    raise AppException(
        status_code=status.HTTP_404_NOT_FOUND,
        error_code="APK_NOT_FOUND",
        message="Android APK file is not available."
    )

@app.get("/downloads/achuppori.apk", tags=["Downloads"], include_in_schema=False)
def download_achuppori_apk_direct():
    return download_achuppori_apk()


# Frontends directory paths
flutter_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "build" / "web"
web_dist = Path(__file__).resolve().parent.parent / "web"

# Mount real Autonomous Printer Flutter Web client at root /
if flutter_dist.exists() and (flutter_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(flutter_dist), html=True), name="flutter-web")
elif web_dist.exists() and (web_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="smartprint-web")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
