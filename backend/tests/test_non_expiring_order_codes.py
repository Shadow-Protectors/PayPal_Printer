from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.db.models.document import Document, DocumentStatus
from app.db.models.order import Order, OrderStatus
from app.db.models.otp import OTP
from app.db.models.refund import Refund
from app.services.otp_service import otp_service
from tests.conftest import checkout_payload, create_sample_pdf


def paid_order(client, station, gateway, filename="permanent-code.pdf"):
    upload = client.post("/api/documents/upload", files={
        "file": (filename, create_sample_pdf(1), "application/pdf")
    })
    assert upload.status_code == 201
    order = client.post("/api/orders", json={
        "document_id": upload.json()["documentId"], "print_server_id": station.id,
        "settings": {"copies": 1},
    })
    assert order.status_code == 201
    order_id = order.json()["id"]
    assert client.post("/api/payments/verify", json=checkout_payload(client, gateway, order_id)).status_code == 200
    return order_id


@pytest.mark.parametrize("printer", ["HP_LaserJet_400_M401dn_F36EC0", "HP_LaserJet_400_M401dn_E9A0F4"])
def test_legacy_elapsed_code_survives_worker_and_releases_once(
    client, test_print_server, db_session, gateway, monkeypatch, printer
):
    from app import worker

    order_id = paid_order(client, test_print_server, gateway)
    initial = client.get(f"/api/orders/{order_id}/otp").json()
    assert initial["expiresAt"] is None
    code = initial["printerOtps"][printer]["otp"]

    row = db_session.query(OTP).filter(OTP.order_id == order_id).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=365)
    order = db_session.get(Order, order_id)
    doc = db_session.get(Document, order.document_id)
    doc.status = DocumentStatus.CLEANUP_PENDING
    db_session.commit()

    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db_session))
    delete_file = Mock()
    monkeypatch.setattr("app.services.cleanup_service.storage_service.delete_file", delete_file)
    worker.run_once()
    delete_file.assert_not_called()
    db_session.refresh(row)
    db_session.refresh(order)
    assert row.active is True
    assert order.status == OrderStatus.WAITING_FOR_OTP
    assert db_session.query(Refund).filter(Refund.order_id == order_id).count() == 0

    refreshed = client.get(f"/api/orders/{order_id}/otp")
    assert refreshed.status_code == 200
    assert refreshed.json()["expiresAt"] is None
    assert refreshed.json()["printerOtps"][printer]["otp"] == code
    recovery = client.get(f"/api/orders/active?order_id={order_id}").json()
    assert recovery["stage"] == "WAITING_FOR_OTP"
    assert recovery["otp"]["expiresAt"] is None

    monkeypatch.setattr("requests.post", Mock(return_value=Mock(status_code=200)))
    release = client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": code})
    assert release.status_code == 200
    db_session.refresh(row)
    assert row.active is False
    assert row.used_at is not None
    assert client.get(f"/api/orders/{order_id}/otp").status_code == 400
    repeated = client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": code})
    assert repeated.status_code == 400
    assert repeated.json()["error"] == "ALREADY_PRINTED"


def test_cancelled_elapsed_code_stays_invalid(client, test_print_server, db_session, gateway):
    order_id = paid_order(client, test_print_server, gateway)
    code = client.get(f"/api/orders/{order_id}/otp").json()["otp"]
    row = db_session.query(OTP).filter(OTP.order_id == order_id).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=365)
    db_session.commit()
    assert client.post(f"/api/orders/{order_id}/cancel").status_code == 200
    assert client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": code}).status_code == 400
    db_session.refresh(row)
    assert row.active is False


def test_new_codes_avoid_active_primary_and_secondary_codes(client, test_print_server, db_session, gateway, monkeypatch):
    first_id = paid_order(client, test_print_server, gateway)
    first = client.get(f"/api/orders/{first_id}/otp").json()
    used = {printer["otp"] for printer in first["printerOtps"].values()}
    choices = (f"{value:06}" for value in range(100000, 100100) if f"{value:06}" not in used)
    fresh = [next(choices), next(choices)]
    generated = iter([first["otp"], first["printerOtps"]["HP_LaserJet_400_M401dn_E9A0F4"]["otp"], fresh[0], fresh[0], fresh[1]])
    monkeypatch.setattr("app.services.otp_service.generate_secure_otp", lambda _: next(generated))
    second_id = paid_order(client, test_print_server, gateway, "another.pdf")
    second = client.get(f"/api/orders/{second_id}/otp").json()
    assert {p["otp"] for p in second["printerOtps"].values()} == set(fresh)
    assert otp_service.get_otp_for_order(db_session, first_id)[0] == first["otp"]


def test_older_secondary_code_remains_discoverable_after_fifty_new_orders(client, test_print_server, db_session, gateway, monkeypatch):
    first_id = paid_order(client, test_print_server, gateway)
    code = client.get(f"/api/orders/{first_id}/otp").json()["printerOtps"]["HP_LaserJet_400_M401dn_E9A0F4"]["otp"]
    for index in range(51):
        paid_order(client, test_print_server, gateway, f"new-{index}.pdf")
    monkeypatch.setattr("requests.post", Mock(return_value=Mock(status_code=200)))
    assert client.post("/api/agent/release-kiosk", headers={"Authorization": "Bearer test-agent-device-token-secret"}, json={"otp": code}).status_code == 200
