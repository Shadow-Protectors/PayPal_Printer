from datetime import datetime, timezone, timedelta
from app.db.models.printer import Printer
from app.db.models.otp import OTP
from app.db.models.order import Order
from app.services.printer_availability import printer_state
from tests.test_department_print_flow import checkout, AGENT


def test_offline_release_preserves_paid_otp(client, test_print_server, gateway, db_session):
    order_id, _ = checkout(client, test_print_server, gateway)
    code = client.get(f'/api/orders/{order_id}/otp').json()['otp']
    for p in db_session.query(Printer):
        p.printer_status = 'OFFLINE'
    db_session.commit()
    result = client.post('/api/agent/release', headers=AGENT, json={'otp': code})
    assert result.status_code == 409
    assert result.json()['error'] == 'PRINTER_UNAVAILABLE'
    otp = db_session.query(OTP).filter_by(order_id=order_id).one()
    assert otp.active and otp.used_at is None
    assert db_session.get(Order, order_id).status.value == 'WAITING_FOR_OTP'
    for p in db_session.query(Printer):
        p.printer_status = 'READY'
    db_session.commit()
    assert client.post('/api/agent/release', headers=AGENT, json={'otp': code}).status_code == 200


def test_stale_heartbeat_never_advertises_ready(test_print_server, db_session):
    p = db_session.query(Printer).first()
    test_print_server.last_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert printer_state(p, test_print_server) == 'OFFLINE'


def test_offline_printer_blocks_payment_initialization(client, test_print_server, gateway, db_session):
    order_id, _ = checkout(client, test_print_server, gateway, paid=False)
    for p in db_session.query(Printer):
        p.printer_status = 'OFFLINE'
    db_session.commit()
    response = client.post('/api/payments/create', json={'orderId': order_id})
    assert response.status_code == 409
    assert response.json()['error'] == 'PRINTER_UNAVAILABLE'


def test_offline_station_blocks_new_checkout(client, test_print_server, db_session, gateway):
    from tests.conftest import create_sample_pdf
    for p in db_session.query(Printer):
        p.printer_status = 'OFFLINE'
    db_session.commit()
    doc = client.post('/api/documents/upload', files={'file': ('one.pdf', create_sample_pdf(1), 'application/pdf')}).json()
    r = client.post('/api/orders', json={'documentId': doc['documentId'], 'printServerId': test_print_server.id})
    assert r.status_code == 409
    assert r.json()['error'] == 'PRINTER_UNAVAILABLE'


def test_heartbeat_returns_only_own_mapped_queue_and_activates_when_ready(client, test_print_server, db_session):
    p = db_session.query(Printer).first()
    p.is_active = False
    p.test_status = 'PENDING'
    p.device_uri = 'ipp://192.0.2.7/ipp/print'
    db_session.commit()
    payload = {'printers': [{'cups_printer_name': p.cups_printer_name, 'device_uri': p.device_uri,
                            'status': 'DISCOVERED'}]}
    response = client.post('/api/agent/heartbeat', headers=AGENT, json=payload)
    assert response.status_code == 200
    assert any(x['device_uri'] == p.device_uri for x in response.json()['assignments'])
    db_session.refresh(p)
    assert not p.is_active and p.printer_status == 'CONFIGURING'
    payload['printers'][0].update(status='READY', supports_color=False, supports_duplex=True)
    client.post('/api/agent/heartbeat', headers=AGENT, json=payload)
    db_session.refresh(p)
    assert p.is_active and p.test_status == 'SUCCESS' and not p.supports_color


def test_customer_order_exposes_offline_printer_message(client, test_print_server, gateway, db_session):
    order_id, _ = checkout(client, test_print_server, gateway)
    code = client.get(f'/api/orders/{order_id}/otp').json()['otp']
    result = client.post('/api/agent/release', headers=AGENT, json={'otp': code})
    assert result.status_code == 200
    for p in db_session.query(Printer):
        p.printer_status = 'OFFLINE'
    db_session.commit()
    data = client.get(f'/api/orders/{order_id}').json()
    assert data['errorCode'] == 'PRINTER_OFFLINE'
    assert 'offline' in data['errorMessage'].lower()
