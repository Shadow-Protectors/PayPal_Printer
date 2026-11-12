import io
import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.main import app

def generate_sample_pdf(num_pages: int = 6) -> bytes:
    """Generate in-memory PDF with specified number of pages."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    for i in range(num_pages):
        c.drawString(100, 750, f"Lecture Slide #{i+1}: Operating Systems Architecture")
        c.drawString(100, 700, "Definition: A kernel manages hardware resources and execution scheduling.")
        c.drawString(100, 650, "Formula: CPU Utilization = Total Busy Time / Total Elapsed Time")
        c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client

def test_full_kiosk_payment_print_loop(client):
    # 1. Upload sample PDF
    pdf_bytes = generate_sample_pdf(6)
    upload_res = client.post(
        "/api/kiosk/upload",
        files={"file": ("lecture_slides.pdf", pdf_bytes, "application/pdf")}
    )
    assert upload_res.status_code == 200, upload_res.text
    data = upload_res.json()
    assert data["original_pages"] == 6
    assert data["full_price"] == "0.60"
    assert data["summary_pages"] >= 1
    assert float(data["summary_price"]) < float(data["full_price"])
    file_id = data["file_id"]

    # 2. Create order (Server-authoritative pricing)
    create_res = client.post(
        "/api/kiosk/create-order",
        json={"file_id": file_id, "mode": "summary", "currency": "USD"}
    )
    assert create_res.status_code == 200, create_res.text
    order_data = create_res.json()
    paypal_order_id = order_data["paypal_order_id"]
    expected_amount = order_data["amount"]
    assert float(expected_amount) > 0

    # 3. Capture order & verify issuance of 6-digit PIN
    capture_res = client.post(
        "/api/kiosk/capture-order",
        json={"paypal_order_id": paypal_order_id}
    )
    assert capture_res.status_code == 200, capture_res.text
    cap_data = capture_res.json()
    assert cap_data["status"] == "PAID"
    pin = cap_data["release_code"]
    assert len(pin.replace("-", "")) == 6

    # 4. Idempotency test: Re-submitting the same capture returns the same PIN
    replay_res = client.post(
        "/api/kiosk/capture-order",
        json={"paypal_order_id": paypal_order_id}
    )
    assert replay_res.status_code == 200
    assert replay_res.json()["release_code"] == pin

    # 5. Claim release code on kiosk simulator
    release_res = client.post(
        "/api/kiosk/release-code",
        json={"release_code": pin}
    )
    assert release_res.status_code == 200, release_res.text
    assert release_res.json()["status"] == "COMPLETED"

    # 6. Single-use test: Reusing the same PIN must fail
    second_claim = client.post(
        "/api/kiosk/release-code",
        json={"release_code": pin}
    )
    assert second_claim.status_code == 400
    assert "already been used" in second_claim.json()["detail"].lower()
