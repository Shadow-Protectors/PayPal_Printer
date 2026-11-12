import json
import pytest

from app.db.models.order import Order, OrderStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.otp import OTP
from app.db.models.print_job import PrintJob
from tests.conftest import create_sample_pdf, checkout_payload, sign_payload


@pytest.fixture
def checkout_order(client, test_print_server):
    upload = client.post('/api/documents/upload', files={
        'file': ('gateway-test.pdf', create_sample_pdf(2), 'application/pdf')
    })
    assert upload.status_code == 201
    response = client.post('/api/orders', json={
        'documentId': upload.json()['documentId'], 'printServerId': test_print_server.id,
        'settings': {'copies': 1}
    })
    assert response.status_code == 201
    return response.json()['id']


def test_gateway_failure_never_returns_invented_order(client, checkout_order, gateway, db_session):
    def unavailable(*args, **kwargs):
        raise ConnectionError('connection unavailable')
    gateway.order.create = unavailable
    response = client.post('/api/payments/create', json={'orderId': checkout_order})
    assert response.status_code == 502
    assert response.json()['error'] == 'GATEWAY_UNAVAILABLE'
    assert db_session.query(Payment).count() == 0
    assert db_session.query(PrintJob).count() == 0


def test_retry_reuses_gateway_order(client, checkout_order, gateway):
    first = client.post('/api/payments/create', json={'orderId': checkout_order})
    second = client.post('/api/payments/create', json={'orderId': checkout_order})
    assert first.json()['razorpayOrderId'] == second.json()['razorpayOrderId']
    assert len(gateway.orders) == 1
    assert first.json()['amountPaise'] == 400


def test_legacy_invented_order_is_repaired(client, checkout_order, gateway, db_session):
    db_session.add(Payment(id='legacy-payment', order_id=checkout_order,
                           razorpay_order_id='order_rzp_invented', amount=4,
                           currency='INR', status=PaymentStatus.PENDING))
    db_session.commit()
    response = client.post('/api/payments/create', json={'orderId': checkout_order})
    assert response.status_code == 201
    assert response.json()['razorpayOrderId'] in gateway.orders
    assert db_session.query(Payment).count() == 1


def test_invalid_signature_cannot_release_printing(client, checkout_order, gateway, db_session):
    payload = checkout_payload(client, gateway, checkout_order)
    payload['razorpaySignature'] = 'test_sig'
    response = client.post('/api/payments/verify', json=payload)
    assert response.status_code == 400
    assert response.json()['error'] == 'INVALID_SIGNATURE'
    assert db_session.query(Order).first().status == OrderStatus.CREATED
    assert db_session.query(OTP).count() == 0
    assert db_session.query(PrintJob).count() == 0


@pytest.mark.parametrize('field,value,code', [
    ('amount', 1, 'PAYMENT_MISMATCH'),
    ('currency', 'USD', 'PAYMENT_MISMATCH'),
    ('order_id', 'order_wrong', 'PAYMENT_MISMATCH'),
    ('status', 'authorized', 'PAYMENT_NOT_CAPTURED'),
    ('amount_refunded', 400, 'PAYMENT_REFUNDED'),
])
def test_capture_evidence_must_match(client, checkout_order, gateway, db_session, field, value, code):
    payload = checkout_payload(client, gateway, checkout_order)
    gateway.payments[payload['razorpayPaymentId']][field] = value
    response = client.post('/api/payments/verify', json=payload)
    assert response.status_code >= 400
    assert response.json()['error'] == code
    assert db_session.query(OTP).count() == 0


def test_repeat_confirmation_preserves_code_and_printing_state(client, checkout_order, gateway, db_session):
    payload = checkout_payload(client, gateway, checkout_order)
    assert client.post('/api/payments/verify', json=payload).status_code == 200
    first = client.get(f'/api/orders/{checkout_order}/otp').json()['otp']
    assert client.post('/api/payments/verify', json=payload).status_code == 200
    assert client.get(f'/api/orders/{checkout_order}/otp').json()['otp'] == first
    assert db_session.query(OTP).count() == 1
    assert db_session.query(PrintJob).count() == 1
    order = db_session.query(Order).first()
    order.status = OrderStatus.PRINTING
    db_session.commit()
    assert client.post('/api/payments/verify', json=payload).json()['status'] == 'PRINTING'
    assert db_session.query(OTP).count() == 1


def test_reconcile_recovers_a_missed_checkout_callback(client, checkout_order, gateway, db_session):
    checkout_payload(client, gateway, checkout_order)
    response = client.post('/api/payments/reconcile', json={'orderId': checkout_order})
    assert response.status_code == 200
    assert response.json()['paid'] is True
    assert db_session.query(PrintJob).count() == 1
    assert db_session.query(OTP).count() == 1
    assert client.post('/api/payments/reconcile', json={'orderId': checkout_order}).json()['paid'] is True
    assert db_session.query(OTP).count() == 1


def test_pending_reconcile_does_not_authorize_printing(client, checkout_order, db_session):
    client.post('/api/payments/create', json={'orderId': checkout_order})
    response = client.post('/api/payments/reconcile', json={'orderId': checkout_order})
    assert response.json()['paid'] is False
    assert db_session.query(OTP).count() == 0


def test_webhook_rejects_fake_signature_and_ignores_uncaptured_events(client, checkout_order, gateway, db_session):
    payload = checkout_payload(client, gateway, checkout_order)
    entity = gateway.payments[payload['razorpayPaymentId']]
    body = json.dumps({'event': 'payment.authorized', 'payload': {'payment': {'entity': entity}}}).encode()
    assert client.post('/api/payments/webhook', content=body,
                       headers={'X-Razorpay-Signature': 'test_sig'}).status_code == 400
    assert client.post('/api/payments/webhook', content=body,
                       headers={'X-Razorpay-Signature': sign_payload(body)}).json()['status'] == 'ignored'
    assert db_session.query(OTP).count() == 0


def test_cancelled_order_cannot_be_reactivated_by_confirmation(client, checkout_order, gateway, db_session):
    payload = checkout_payload(client, gateway, checkout_order)
    assert client.post(f'/api/orders/{checkout_order}/cancel').status_code == 200
    response = client.post('/api/payments/verify', json=payload)
    assert response.status_code == 409
    assert db_session.query(Order).first().status == OrderStatus.CANCELLED
    assert db_session.query(OTP).count() == 0
