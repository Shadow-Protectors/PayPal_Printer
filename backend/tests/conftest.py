import os
# Tests never initialize the configured college or local installation database.
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['ENVIRONMENT'] = 'testing'
os.environ['ROOT_PATH'] = ''
os.environ['ADMIN_EMAIL'] = ''
os.environ['ADMIN_PASSWORD'] = ''
os.environ['ALLOWED_ORIGINS'] = '["https://nec.edu.in"]'

import pytest
import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.config.database import Base
from app.db.session import get_db
from app.db.models.user import User, UserRole
from app.db.models.print_server import PrintServer, PrintServerStatus
from app.config.security import hash_password, hash_token

# In-memory SQLite for fast, isolated testing
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def gateway(monkeypatch):
    """Keep gateway I/O isolated while exercising real signature checks."""
    from app.config.settings import settings
    from app.services.payment_service import PaymentService
    orders = {}
    payments = {}

    def create(data, **kwargs):
        entity = {**data, "id": f"order_{uuid.uuid4().hex}"}
        orders[entity["id"]] = entity
        return entity

    def capture(order_id, payment_id=None):
        payment_id = payment_id or f"pay_{uuid.uuid4().hex}"
        order = orders[order_id]
        entity = {"id": payment_id, "order_id": order_id, "amount": order["amount"],
                  "currency": order["currency"], "status": "captured", "amount_refunded": 0}
        payments[payment_id] = entity
        return entity

    fake = SimpleNamespace(
        order=SimpleNamespace(create=create, payments=lambda order_id, **kw: {
            "items": [p for p in payments.values() if p["order_id"] == order_id]
        }),
        payment=SimpleNamespace(fetch=lambda payment_id, **kw: payments[payment_id],
                                refund=lambda *args, **kw: {"id": f"rfnd_{uuid.uuid4().hex}", "status": "processed"}),
        capture=capture, orders=orders, payments=payments,
    )
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_unit")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "unit-test-secret")
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "unit-webhook-secret")
    monkeypatch.setattr(PaymentService, "_gateway_client", staticmethod(lambda: fake))
    monkeypatch.setattr("razorpay.Client", lambda *args, **kwargs: fake)
    return fake


@pytest.fixture(autouse=True)
def isolate_email_delivery(monkeypatch):
    from app.services.email_service import email_service
    monkeypatch.setattr(email_service, "send_otp", lambda *args, **kwargs: True)
    monkeypatch.setattr(email_service, "send_order_status_notification", lambda *args, **kwargs: True)
    yield



def sign_payload(body, secret="unit-webhook-secret"):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def checkout_payload(client, gateway, order_id):
    response = client.post("/api/payments/create", json={"orderId": order_id})
    assert response.status_code == 201
    gateway_order = response.json()["razorpayOrderId"]
    entity = gateway.capture(gateway_order)
    return {"orderId": order_id, "razorpayOrderId": gateway_order,
            "razorpayPaymentId": entity["id"],
            "razorpaySignature": sign_payload(f"{gateway_order}|{entity['id']}".encode(), "unit-test-secret")}

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def client(db_session):
    from app.utils.rate_limit import auth_limiter
    auth_limiter.entries.clear()
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, headers={"X-Customer-Session": f"sess_{uuid.uuid4().hex}"}) as test_client:
        yield test_client
    app.dependency_overrides.clear()

@pytest.fixture
def test_user(db_session):
    user = User(
        email="student@university.edu",
        full_name="Test Student",
        password_hash=hash_password("SecurePass123!"),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user

@pytest.fixture
def test_agent_token():
    return "test-agent-device-token-secret"

@pytest.fixture
def test_print_server(db_session, test_agent_token):
    server = PrintServer(
        id="PRINT-SERVER-001",
        name="Main Library Print Station",
        location="Library Floor 1",
        device_token_hash=hash_token(test_agent_token),
        status=PrintServerStatus.ONLINE
    )
    db_session.add(server)
    server.last_heartbeat = datetime.now(timezone.utc)
    db_session.commit()
    db_session.refresh(server)
    from app.db.models.printer import Printer
    for idx, name in enumerate(("HP_LaserJet_400_M401dn_F36EC0", "HP_LaserJet_400_M401dn_E9A0F4")):
        db_session.add(Printer(id=f"TEST-PRINTER-{idx}", server_id=server.id, cups_printer_name=name,
                               display_name=f"Test printer {idx + 1}", is_enabled=True, is_active=True, printer_status="READY", last_seen=datetime.now(timezone.utc)))
    db_session.commit()
    # Tests using the compatibility kiosk route still exercise authenticated station release.
    return server

import io
from pypdf import PdfWriter

def create_sample_pdf(page_count: int = 3) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

def get_auth_token(client, test_user):
    login_res = client.post("/api/auth/login", json={
        "email": test_user.email,
        "password": "SecurePass123!"
    })
    return login_res.json()["access_token"]

@pytest.fixture(autouse=True)
def isolate_station_rate_limits(monkeypatch):
    from app.services import otp_service
    monkeypatch.setattr(otp_service, "_otp_rate_limiter", otp_service.OTPRateLimiter())
