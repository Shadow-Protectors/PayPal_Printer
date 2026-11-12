import json
from tests.conftest import create_sample_pdf, sign_payload

def test_full_payment_otp_and_agent_workflow(client, test_print_server, test_agent_token):
    # 1. Upload Document WITHOUT LOGIN
    pdf_bytes = create_sample_pdf(3)
    up_res = client.post(
        "/api/documents/upload",
        files={"file": ("report.pdf", pdf_bytes, "application/pdf")}
    )
    assert up_res.status_code == 201
    doc_id = up_res.json()["documentId"]

    # 2. Create Order WITHOUT LOGIN
    order_res = client.post(
        "/api/orders",
        json={
            "document_id": doc_id,
            "print_server_id": test_print_server.id,
            "settings": {"copies": 1, "page_range": "1-3"}
        }
    )
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]
    order_amount = order_res.json()["amount"]
    amount_paise = int(order_amount * 100)

    # 3. Create Payment WITHOUT LOGIN
    pay_res = client.post(
        "/api/payments/create",
        json={"order_id": order_id}
    )
    assert pay_res.status_code == 201
    rzp_order_id = pay_res.json()["razorpayOrderId"]

    # 4. Simulate Webhook (Razorpay to FastAPI)
    webhook_payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test123",
                    "order_id": rzp_order_id,
                    "amount": amount_paise,
                    "status": "captured",
                    "currency": "INR"
                }
            }
        }
    }
    raw_webhook = json.dumps(webhook_payload).encode('utf-8')
    wh_res = client.post(
        "/api/payments/webhook",
        headers={"X-Razorpay-Signature": sign_payload(raw_webhook), "Content-Type": "application/json"},
        content=raw_webhook
    )
    assert wh_res.status_code == 200
    assert wh_res.json()["status"] == "success"

    # Verify idempotency: duplicate webhook should succeed gracefully
    wh_dup = client.post(
        "/api/payments/webhook",
        headers={"X-Razorpay-Signature": sign_payload(raw_webhook), "Content-Type": "application/json"},
        content=raw_webhook
    )
    assert wh_dup.status_code == 200

    # 5. User checks OTP directly on phone WITHOUT LOGIN
    otp_res = client.get(f"/api/orders/{order_id}/otp")
    assert otp_res.status_code == 200
    otp_code = otp_res.json()["otp"]
    assert len(otp_code) == 6

    # 6. Agent Heartbeat
    hb_res = client.post(
        "/api/agent/heartbeat",
        headers={"Authorization": f"Bearer {test_agent_token}"},
        json={"printerState": "READY", "paperState": "AVAILABLE"}
    )
    assert hb_res.status_code == 200
    assert hb_res.json()["status"] == "OK"

    # 7. Agent enters wrong OTP at physical kiosk -> 400
    wrong_res = client.post(
        "/api/agent/release",
        headers={"Authorization": f"Bearer {test_agent_token}"},
        json={"otp": "000000"}
    )
    assert wrong_res.status_code == 400
    assert wrong_res.json()["error"] == "INVALID_OTP"

    # 8. Agent enters correct OTP at physical kiosk -> 200 and RELEASED
    rel_res = client.post(
        "/api/agent/release",
        headers={"Authorization": f"Bearer {test_agent_token}"},
        json={"otp": otp_code}
    )
    assert rel_res.status_code == 200
    job_data = rel_res.json()
    assert job_data["status"] == "RELEASED"
    job_id = job_data["jobId"]
    assert "storageKey" in job_data

    # 9. Agent polls jobs -> released job should appear
    jobs_res = client.get(
        "/api/agent/jobs",
        headers={"Authorization": f"Bearer {test_agent_token}"}
    )
    assert jobs_res.status_code == 200
    assert any(j["jobId"] == job_id for j in jobs_res.json())

    # 10. Agent reports status: PRINTING
    status_p = client.post(
        f"/api/agent/jobs/{job_id}/status",
        headers={"Authorization": f"Bearer {test_agent_token}"},
        json={"status": "PRINTING", "cupsJobId": "cups-42"}
    )
    assert status_p.status_code == 200

    # 11. Agent reports status: COMPLETED
    status_c = client.post(
        f"/api/agent/jobs/{job_id}/status",
        headers={"Authorization": f"Bearer {test_agent_token}"},
        json={"status": "COMPLETED"}
    )
    assert status_c.status_code == 200

    # 12. Verify final order status is COMPLETED
    order_final = client.get(f"/api/orders/{order_id}")
    assert order_final.status_code == 200
    assert order_final.json()["status"] == "COMPLETED"


def test_agent_heartbeat_records_software_version(client, test_agent_token, test_print_server, db_session):
    hb_res = client.post(
        "/api/agent/heartbeat",
        headers={"Authorization": f"Bearer {test_agent_token}"},
        json={
            "printerState": "READY",
            "paperState": "AVAILABLE",
            "version": "1.8.4",
            "timestamp": "2026-10-28T10:00:00Z"
        }
    )
    assert hb_res.status_code == 200
    db_session.refresh(test_print_server)
    assert test_print_server.software_version == "1.8.4"

