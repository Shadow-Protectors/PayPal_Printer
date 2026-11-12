from datetime import datetime, timezone
from unittest.mock import Mock
from app.config.security import hash_token
from app.db.models.print_server import PrintServer, PrintServerStatus
from app.db.models.printer import Printer
from app.db.models.print_job import PrintJob, PrintJobStatus
from app.db.models.order import Order, OrderStatus
from app.db.models.otp import OTP
from app.db.models.refund import Refund, RefundStatus
from app.services.settings_service import load_platform_settings
from tests.conftest import create_sample_pdf, checkout_payload

AGENT = {"Authorization": "Bearer test-agent-device-token-secret"}


def checkout(client, station, gateway, paid=True):
    uploaded = client.post("/api/documents/upload", files={"file": ("flow.pdf", create_sample_pdf(2), "application/pdf")})
    assert uploaded.status_code == 201
    response = client.post("/api/orders", json={"documentId": uploaded.json()["documentId"], "printServerId": station.id})
    assert response.status_code == 201
    order_id = response.json()["id"]
    if paid:
        assert client.post("/api/payments/verify", json=checkout_payload(client, gateway, order_id)).status_code == 200
    return order_id, uploaded.json()["documentId"]


def test_unpaid_order_cannot_obtain_or_release_code(client, test_print_server, gateway, db_session):
    order_id, _ = checkout(client, test_print_server, gateway, paid=False)
    assert client.get(f"/api/orders/{order_id}/otp").json()["error"] == "PAYMENT_NOT_COMPLETED"
    assert db_session.query(OTP).filter(OTP.order_id == order_id).count() == 0
    assert db_session.get(Order, order_id).status == OrderStatus.CREATED


def test_station_ownership_and_atomic_claim(client, test_print_server, gateway, db_session):
    other = PrintServer(id="OTHER-STATION", name="Other department", location="Other lab",
                        device_token_hash=hash_token("other-token"), status=PrintServerStatus.ONLINE)
    db_session.add(other)
    db_session.commit()
    order_id, doc_id = checkout(client, test_print_server, gateway)
    code = client.get(f"/api/orders/{order_id}/otp").json()["otp"]
    assert client.post("/api/agent/release-kiosk", json={"otp": code}).status_code == 401
    wrong = client.post("/api/agent/release", headers={"Authorization": "Bearer other-token"}, json={"otp": code})
    assert wrong.json()["error"] == "WRONG_STATION"
    assert db_session.get(Order, order_id).status == OrderStatus.WAITING_FOR_OTP
    release = client.post("/api/agent/release", headers=AGENT, json={"otp": code})
    assert release.status_code == 200
    job_id = release.json()["jobId"]
    assert "session_token" not in release.json()["settings"]
    job = db_session.get(PrintJob, job_id)
    assert job.printer_id is not None
    assert client.post(f"/api/agent/jobs/{job_id}/claim", headers={"Authorization": "Bearer other-token"}).json()["claimed"] is False
    assert client.post(f"/api/agent/jobs/{job_id}/claim", headers=AGENT).json()["claimed"] is True
    assert client.post(f"/api/agent/jobs/{job_id}/claim", headers=AGENT).json()["claimed"] is False
    assert not client.get("/api/agent/jobs", headers=AGENT).json()
    key = release.json()["storageKey"]
    assert client.get(f"/api/agent/file/{key}", headers={"Authorization": "Bearer other-token"}).status_code == 404
    assert client.get(f"/api/agent/file/{key}", headers=AGENT).status_code == 200


def test_customer_isolation_includes_documents_payments_and_recovery(client, test_print_server, gateway):
    order_id, doc_id = checkout(client, test_print_server, gateway)
    stranger = {"X-Customer-Session": "sess_unrelated_customer"}
    for path in (f"/api/orders/{order_id}", f"/api/orders/{order_id}/otp", f"/api/orders/active?order_id={order_id}", f"/api/documents/{doc_id}"):
        assert client.get(path, headers=stranger).status_code == 404
    assert client.post("/api/payments/reconcile", headers=stranger, json={"orderId": order_id}).status_code == 404
    assert client.delete(f"/api/documents/{doc_id}", headers=stranger).status_code == 404
    assert client.get("/api/orders", headers=stranger).json() == []
    settings = client.get(f"/api/orders/{order_id}").json()["printSettings"]
    assert "session_token" not in settings
    assert all("otp_hash" not in info and "otp" not in info for info in settings["printer_otps"].values())


def test_codes_for_three_real_printers_and_regeneration(client, test_print_server, gateway, db_session):
    db_session.add(Printer(id="THIRD", server_id=test_print_server.id, cups_printer_name="Actual_Third_Queue", display_name="Third", is_enabled=True))
    db_session.commit()
    order_id, _ = checkout(client, test_print_server, gateway)
    codes = client.get(f"/api/orders/{order_id}/otp").json()["printerOtps"]
    assert len(codes) == 3
    assert len({info["otp"] for info in codes.values()}) == 3
    assert "Actual_Third_Queue" in codes
    assert client.post(f"/api/orders/{order_id}/printer", json={"cups_printer_name": "Printer_2"}).json()["error"] == "INVALID_PRINTER"
    from app.services.otp_service import otp_service
    otp_service.generate_and_store_otp(db_session, order_id)
    db_session.commit()
    assert db_session.query(OTP).filter(OTP.order_id == order_id).count() == 1


def test_failure_events_retry_only_before_submission(client, test_print_server, gateway, db_session):
    order_id, _ = checkout(client, test_print_server, gateway)
    code = client.get(f"/api/orders/{order_id}/otp").json()["otp"]
    job_id = client.post("/api/agent/release", headers=AGENT, json={"otp": code}).json()["jobId"]
    client.post(f"/api/agent/jobs/{job_id}/claim", headers=AGENT)
    event = {"status": "FAILED", "errorCode": "FILE_NOT_FOUND", "eventId": "download-failure"}
    for _ in range(2):
        assert client.post(f"/api/agent/jobs/{job_id}/status", headers=AGENT, json=event).status_code == 200
    job = db_session.get(PrintJob, job_id)
    assert job.retry_count == 1 and job.status == PrintJobStatus.RELEASED
    assert client.post(f"/api/agent/jobs/{job_id}/claim", headers=AGENT).json()["claimed"]
    assert client.post(f"/api/agent/jobs/{job_id}/status", headers=AGENT, json={"status": "FAILED", "cupsJobId": "42", "errorCode": "PRINT_ERROR"}).status_code == 200
    db_session.refresh(job)
    assert job.status == PrintJobStatus.FINAL_FAILED


def test_refund_network_failure_is_never_reported_success(client, test_print_server, gateway, db_session):
    order_id, _ = checkout(client, test_print_server, gateway)
    gateway.payment.refund = Mock(side_effect=TimeoutError("gateway unavailable"))
    result = client.post(f"/api/orders/{order_id}/cancel")
    assert result.status_code == 502
    assert db_session.get(Order, order_id).status == OrderStatus.CANCELLED
    refund = db_session.query(Refund).filter(Refund.order_id == order_id).one()
    assert refund.status == RefundStatus.FAILED
    assert refund.razorpay_refund_id is None


def test_agent_heartbeat_validates_usb_printer_without_inbound_network(client, test_print_server, db_session):
    printer = db_session.get(Printer, "TEST-PRINTER-0")
    printer.device_uri = "usb://HP/LaserJet"
    db_session.commit()
    assert client.post("/api/agent/heartbeat", headers=AGENT, json={"printerState": "READY", "paperState": "AVAILABLE",
        "printers": [{"cups_printer_name": printer.cups_printer_name, "device_uri": printer.device_uri, "status": "READY", "jobs": 0}]}).status_code == 200
    from app.services.admin_service import admin_service
    assert admin_service.test_printer_connection(printer.id, db_session).success is True
    assert admin_service.get_agent_cups_printers(test_print_server.id, db_session)[0].cups_printer_name == printer.cups_printer_name


def test_persisted_pricing_applies_after_reload(client, test_print_server, gateway, db_session, monkeypatch):
    from app.config.settings import settings
    from app.schemas.admin import AdminSystemSettingsUpdate
    from app.services.settings_service import save_platform_settings
    monkeypatch.setattr(settings, "PER_PAGE_RATE", 2.0)
    monkeypatch.setattr(settings, "BASE_FEE", 0.0)
    save_platform_settings(db_session, AdminSystemSettingsUpdate(per_page_rate=3.25, base_fee=1.0))
    load_platform_settings(db_session)
    order_id, _ = checkout(client, test_print_server, gateway, paid=False)
    assert client.get(f"/api/orders/{order_id}").json()["amount"] == 7.5


def test_pending_gateway_refund_completes_through_worker(client, test_print_server, gateway, db_session):
    from types import SimpleNamespace
    from app.db.models.payment import Payment, PaymentStatus
    from app.services.refund_service import refund_service
    order_id, _ = checkout(client, test_print_server, gateway)
    gateway.payment.refund = Mock(return_value={"id": "rfnd_PendingFlow", "status": "pending"})
    result = client.post(f"/api/orders/{order_id}/cancel")
    assert result.status_code == 200
    assert result.json()["refundStatus"] == "PROCESSING"
    payment = db_session.query(Payment).filter(Payment.order_id == order_id).one()
    assert payment.status == PaymentStatus.CAPTURED
    gateway.refund = SimpleNamespace(fetch=Mock(return_value={"id": "rfnd_PendingFlow", "status": "processed",
        "payment_id": payment.razorpay_payment_id, "amount": 400}))
    refund_service.reconcile_pending(db_session)
    assert db_session.get(Order, order_id).status == OrderStatus.REFUNDED
    assert payment.status == PaymentStatus.REFUNDED
    assert db_session.query(Refund).filter(Refund.order_id == order_id).one().status == RefundStatus.COMPLETED


def test_sqlite_upgrade_adds_ownership_and_status_columns(tmp_path):
    from sqlalchemy import create_engine, text, inspect
    from app.db.migrate import sync_schema
    engine = create_engine("sqlite:///" + (tmp_path / "upgrade.sqlite3").as_posix())
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE documents (id VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE print_jobs (id VARCHAR(64) PRIMARY KEY)"))
    sync_schema(engine)
    inspector = inspect(engine)
    assert "session_token" in {column["name"] for column in inspector.get_columns("documents")}
    assert "last_status_event" in {column["name"] for column in inspector.get_columns("print_jobs")}
    assert inspector.has_table("platform_settings")
    engine.dispose()
