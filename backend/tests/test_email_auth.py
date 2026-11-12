import pytest
import uuid

@pytest.fixture(autouse=True)
def isolate_email_delivery(monkeypatch):
    from app.services.auth_service import auth_service
    from app.services.email_service import email_service
    auth_service._email_otps.clear()
    monkeypatch.setattr(email_service, "send_otp", lambda *args: True)
    yield
    auth_service._email_otps.clear()


def test_email_otp_flow_and_student_auth(client, test_print_server, test_agent_token, monkeypatch, gateway):
    uid = uuid.uuid4().hex[:8]
    test_email = f"student_otp_{uid}@example.com"
    test_roll = f"ROLL_{uid.upper()}"

    # 1. Login with unregistered email should return 404
    resp = client.post("/api/auth/send-otp", json={"email": test_email, "purpose": "login"})
    assert resp.status_code == 404
    assert resp.json()["error"] == "USER_NOT_FOUND"

    # 2. Signup OTP request for new email should succeed
    resp = client.post("/api/auth/send-otp", json={"email": test_email, "purpose": "signup"})
    assert resp.status_code == 200
    data = resp.json()
    assert "email" in data
    assert data["email"] == test_email

    # Retrieve actual generated 6-digit OTP from auth_service memory store
    from app.services.auth_service import auth_service
    assert test_email in auth_service._email_otps
    otp = auth_service._email_otps[test_email]["otp"]
    assert len(otp) == 6

    # 3. Verify OTP
    resp = client.post("/api/auth/verify-otp", json={"email": test_email, "otp": otp})
    assert resp.status_code == 200
    assert resp.json()["valid"] is True

    # 4. Student signup
    signup_payload = {
        "full_name": "Test Student",
        "roll_number": test_roll,
        "email": test_email,
        "department": "Computer Science (CSE)",
        "otp": otp
    }
    resp = client.post("/api/auth/student/signup", json=signup_payload)
    assert resp.status_code == 201
    auth_data = resp.json()
    assert "access_token" in auth_data
    assert auth_data["user"]["email"] == test_email
    assert auth_data["user"]["roll_number"] == test_roll
    assert "phone" not in auth_data["user"]

    token = auth_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 5. Fetch /me profile
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == test_email
    assert "phone" not in resp.json()

    # 6. Student login with email: request login OTP
    resp = client.post("/api/auth/send-otp", json={"email": test_email, "purpose": "login"})
    assert resp.status_code == 200
    login_otp = auth_service._email_otps[test_email]["otp"]
    assert len(login_otp) == 6

    login_payload = {
        "email": test_email,
        "otp": login_otp
    }
    resp = client.post("/api/auth/student/login", json=login_payload)
    assert resp.status_code == 200
    assert "access_token" in resp.json()
    assert resp.json()["user"]["email"] == test_email

    # Codes are single use, refresh keeps the session, logout revokes refresh.
    assert client.post("/api/auth/student/login", json=login_payload).status_code == 400
    refresh_payload = {"refresh_token": resp.json()["refresh_token"]}
    refreshed = client.post("/api/auth/refresh", json=refresh_payload)
    assert refreshed.status_code == 200
    assert client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {refreshed.json()['access_token']}"
    }).json()["email"] == test_email

    # Continue from login into the complete customer printing workflow.
    from app.config.settings import settings
    from tests.conftest import create_sample_pdf, checkout_payload
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    upload = client.post("/api/documents/upload", files={
        "file": ("student-report.pdf", create_sample_pdf(5), "application/pdf")
    })
    assert upload.status_code == 201
    order_response = client.post("/api/orders", headers=headers, json={
        "document_id": upload.json()["documentId"],
        "print_server_id": test_print_server.id,
        "settings": {"copies": 1, "page_range": "1-5"}
    })
    assert order_response.status_code == 201
    order = order_response.json()
    assert order["userId"] == auth_data["user"]["id"]
    assert order["rollNumber"] == test_roll
    assert order["totalPages"] == 5
    payment = client.post("/api/payments/create", headers=headers, json={"order_id": order["id"]})
    assert payment.status_code == 201
    paid = client.post("/api/payments/verify", headers=headers,
                       json=checkout_payload(client, gateway, order["id"]))
    assert paid.status_code == 200
    recovery = client.get("/api/orders/active", headers=headers).json()
    assert recovery["order"]["id"] == order["id"]
    assert recovery["stage"] == "WAITING_FOR_OTP"
    release = client.post("/api/agent/release", json={"otp": recovery["otp"]["otp"]},
                          headers={"Authorization": f"Bearer {test_agent_token}"})
    assert release.status_code == 200
    job_id = release.json()["jobId"]
    for stage in ("PRINTING", "COMPLETED"):
        assert client.post(f"/api/agent/jobs/{job_id}/status", json={"status": stage},
                           headers={"Authorization": f"Bearer {test_agent_token}"}).status_code == 200
    history = client.get("/api/orders/my", headers=headers)
    assert history.status_code == 200
    assert history.json()[0]["status"] == "COMPLETED"
    assert client.post("/api/auth/logout", json=refresh_payload).status_code == 200
    assert client.post("/api/auth/refresh", json=refresh_payload).status_code == 401


def test_email_delivery_failure_is_reported(client, monkeypatch):
    from app.services.email_service import email_service
    from app.services.auth_service import auth_service
    monkeypatch.setattr(email_service, "send_otp", lambda *args: False)
    email = "delivery-failed@example.com"
    response = client.post("/api/auth/send-otp", json={"email": email, "purpose": "signup"})
    assert response.status_code == 503
    assert response.json()["error"] == "EMAIL_DELIVERY_FAILED"
    assert "otp" not in auth_service._email_otps[email]


def test_missing_smtp_credentials_does_not_report_delivery(monkeypatch):
    from app.config.settings import settings
    from app.services.email_service import EmailService
    monkeypatch.setattr(settings, "SMTP_USER", "")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "")
    assert EmailService._send_smtp("student@example.com", "654321") is False


def test_duplicate_roll_does_not_consume_signup_code(client, db_session, test_user):
    from app.services.auth_service import auth_service
    test_user.roll_number = "EXISTING"
    db_session.commit()
    email = "another-student@example.com"
    client.post("/api/auth/send-otp", json={"email": email, "purpose": "signup"})
    otp = auth_service._email_otps[email]["otp"]
    payload = {"full_name": "Another Student", "roll_number": "EXISTING",
               "email": email, "department": "CSE", "otp": otp}
    response = client.post("/api/auth/student/signup", json=payload)
    assert response.status_code == 400
    assert response.json()["error"] == "ROLL_EXISTS"
    payload["roll_number"] = "NEWROLL"
    assert client.post("/api/auth/student/signup", json=payload).status_code == 201
