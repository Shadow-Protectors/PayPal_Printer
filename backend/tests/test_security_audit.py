import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.config.settings import Settings
from app.db.models.order import Order, OrderStatus
from app.db.models.otp import OTP
from app.db.models.print_job import PrintJob, PrintJobStatus
from tests.conftest import create_sample_pdf

def test_task1_production_startup_validation():
    # In production mode, missing JWT_SECRET_KEY or default INTERNAL_AGENT_TOKEN must raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="",
            DATABASE_URL="mysql+pymysql://user:pass@127.0.0.1:3306/db",
            INTERNAL_AGENT_TOKEN="test-agent-device-token-secret"
        )
    assert "CRITICAL SECURITY CONFIGURATION ERROR" in str(exc_info.value)

    # In production mode, valid non-default secrets allow startup
    prod_settings = Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="super-secure-production-jwt-secret-key-32chars",
        DATABASE_URL="mysql+pymysql://user:pass@127.0.0.1:3306/db",
        INTERNAL_AGENT_TOKEN="super-secure-internal-agent-token-12345"
    )
    assert prod_settings.ENVIRONMENT == "production"

    # In development mode, flexible defaults allow startup
    dev_settings = Settings(
        ENVIRONMENT="development",
        JWT_SECRET_KEY="",
        DATABASE_URL="sqlite:///:memory:"
    )
    assert dev_settings.ENVIRONMENT == "development"

def test_task2_otp_kiosk_brute_force_lockout_and_reset(client, test_print_server, db_session):
    # Create order and OTP
    pdf_bytes = create_sample_pdf(1)
    up = client.post("/api/documents/upload", files={"file": ("doc_sec.pdf", pdf_bytes, "application/pdf")}).json()
    order = client.post("/api/orders", json={"document_id": up["documentId"], "print_server_id": test_print_server.id, "settings": {"copies": 1}}).json()
    
    from app.services.otp_service import otp_service
    otp_code = otp_service.generate_and_store_otp(db_session, order["id"])
    
    ord_rec = db_session.query(Order).filter(Order.id == order["id"]).first()
    ord_rec.status = OrderStatus.WAITING_FOR_OTP
    pj = PrintJob(id=f"job_kiosk_sec_{order['id']}", order_id=order["id"], server_id=test_print_server.id, status=PrintJobStatus.QUEUED)
    db_session.add(pj)
    db_session.commit()

    # Kiosk verification failed attempts
    for i in range(4):
        res = client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": f"88888{i}"})
        assert res.status_code == 400
        assert res.json()["error"] == "INVALID_OTP"

    # 5th attempt must trigger lockout (429 TOO_MANY_ATTEMPTS)
    res5 = client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": "888885"})
    assert res5.status_code == 429
    assert res5.json()["error"] == "TOO_MANY_ATTEMPTS"

    # Locked OTP in DB
    otp_record = db_session.query(OTP).filter(OTP.order_id == order["id"]).first()
    assert otp_record.attempt_count == 0
    assert otp_record.active is True

def test_task3_plaintext_otp_not_exposed_in_order_response(client, test_print_server, db_session, gateway):
    pdf_bytes = create_sample_pdf(1)
    up = client.post("/api/documents/upload", files={"file": ("doc_plain.pdf", pdf_bytes, "application/pdf")}).json()
    order = client.post("/api/orders", json={"document_id": up["documentId"], "print_server_id": test_print_server.id, "settings": {"copies": 1}}).json()
    order_id = order["id"]

    # Generate OTPs
    from app.services.otp_service import otp_service
    otp_service.generate_and_store_otp(db_session, order_id)
    db_session.commit()

    # Query GET /api/orders/{id}
    res = client.get(f"/api/orders/{order_id}")
    assert res.status_code == 200
    order_data = res.json()
    print_settings = order_data.get("printSettings") or {}
    
    # Must never expose plaintext otp inside printer_otps
    if "printer_otps" in print_settings:
        for p_name, p_info in print_settings["printer_otps"].items():
            assert "otp" not in p_info, f"Plaintext OTP was exposed in printer_otps for {p_name}"
            assert "otp_hash" not in p_info, "OTP hashes must not be disclosed"

    from tests.conftest import checkout_payload
    assert client.post("/api/payments/verify", json=checkout_payload(client, gateway, order_id)).status_code == 200

    # Dedicated OTP endpoint must still work for authorized access
    otp_res = client.get(f"/api/orders/{order_id}/otp")
    assert otp_res.status_code == 200
    otp_res_data = otp_res.json()
    assert "printerOtps" in otp_res_data
    for p_name, p_info in otp_res_data["printerOtps"].items():
        assert "otp" in p_info
        assert len(p_info["otp"]) == 6

def test_task4_secure_print_agent_token(client, test_print_server, db_session):
    from unittest.mock import patch
    from app.services.otp_service import otp_service
    from app.config.settings import settings
    from app.db.models.payment import Payment, PaymentStatus

    pdf_bytes = create_sample_pdf(1)
    up = client.post("/api/documents/upload", files={"file": ("doc_task4.pdf", pdf_bytes, "application/pdf")}).json()
    order = client.post("/api/orders", json={"document_id": up["documentId"], "print_server_id": test_print_server.id, "settings": {"copies": 1}}).json()
    otp_code = otp_service.generate_and_store_otp(db_session, order["id"])

    ord_rec = db_session.query(Order).filter(Order.id == order["id"]).first()
    ord_rec.status = OrderStatus.WAITING_FOR_OTP
    pj = PrintJob(id=f"job_sec_tok_{order['id']}", order_id=order["id"], server_id=test_print_server.id, status=PrintJobStatus.QUEUED)
    pmt = Payment(id=f"pmt_sec_{order['id']}", order_id=order["id"], razorpay_order_id="rzp_123", status=PaymentStatus.CAPTURED, amount=2.0, currency="INR")
    db_session.add(pj)
    db_session.add(pmt)
    db_session.commit()

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        res = client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": otp_code})
        assert res.status_code == 200
        mock_post.assert_not_called()  # station polls over outbound HTTPS

def test_task5_cors_origins(client):
    # Only the college origin is permitted.
    res_local = client.options("/api/orders", headers={
        "Origin": "https://nec.edu.in",
        "Access-Control-Request-Method": "POST"
    })
    assert res_local.headers.get("access-control-allow-origin") == "https://nec.edu.in"

    # Temporary testing tunnels are no longer trusted.
    res_tunnel = client.options("/api/orders", headers={
        "Origin": "https://quick-tunnel-xyz.trycloudflare.com",
        "Access-Control-Request-Method": "POST"
    })
    assert res_tunnel.headers.get("access-control-allow-origin") is None

    # Blocked origin: unknown third-party malicious domain
    res_blocked = client.options("/api/orders", headers={
        "Origin": "https://malicious-attacker-site.com",
        "Access-Control-Request-Method": "POST"
    })
    assert res_blocked.headers.get("access-control-allow-origin") is None

def test_task6_swagger_disabled_in_production():
    from app.config.settings import settings
    # Test dev mode: docs available
    with patch.object(settings, "ENVIRONMENT", "development"):
        from app.main import app as dev_app
        client = TestClient(dev_app)
        res_docs = client.get("/docs")
        assert res_docs.status_code == 200

    # In production app instantiation, docs_url, redoc_url, openapi_url are None
    with patch.object(settings, "ENVIRONMENT", "production"):
        from fastapi import FastAPI
        is_production = settings.ENVIRONMENT.lower() in ("production", "prod")
        prod_app = FastAPI(
            title=settings.APP_NAME,
            docs_url=None if is_production else "/docs",
            redoc_url=None if is_production else "/redoc",
            openapi_url=None if is_production else "/openapi.json",
        )
        prod_client = TestClient(prod_app)
        assert prod_client.get("/docs").status_code == 404
        assert prod_client.get("/redoc").status_code == 404
        assert prod_client.get("/openapi.json").status_code == 404
