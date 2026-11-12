import pytest
from app.services.paypal_service import PayPalService

def test_paypal_service_mock_mode():
    service = PayPalService(client_id="mock_id", client_secret="mock_secret")
    assert not service.is_configured()
    
    # Test token
    token = service.get_access_token()
    assert token == "MOCK_SANDBOX_ACCESS_TOKEN"

    # Test order creation
    order = service.create_order("0.40", "USD")
    assert order["status"] == "CREATED"
    assert order["id"].startswith("MOCK-PAYPAL-")
    assert order["purchase_units"][0]["amount"]["value"] == "0.40"

    # Test capture
    capture = service.capture_order(order["id"])
    assert capture["status"] == "COMPLETED"

    # Test verification
    is_valid = service.verify_capture(capture, expected_amount="0.40", expected_currency="USD")
    assert is_valid is True

    # Test tampered amount verification
    tampered_valid = service.verify_capture(capture, expected_amount="5.00", expected_currency="USD")
    assert tampered_valid is False
