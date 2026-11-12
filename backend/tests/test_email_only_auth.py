import pytest

from app.db.models.user import User


@pytest.mark.parametrize("path, payload", [
    ("/api/auth/send-otp", {"phone": "9876543210", "purpose": "signup"}),
    ("/api/auth/verify-otp", {"phone": "9876543210", "otp": "123456"}),
    ("/api/auth/student/login", {"phone": "9876543210", "otp": "123456"}),
    ("/api/auth/send-otp", {"email": "9876543210", "purpose": "signup"}),
    ("/api/auth/send-otp", {"email": "student@example.com", "phone": "9876543210", "purpose": "signup"}),
    ("/api/auth/student/signup", {"email": "student@example.com", "phone": "9876543210",
       "full_name": "Test Student", "roll_number": "EMAIL_ONLY", "department": "CSE", "otp": "123456"}),
])
def test_auth_requires_email_and_rejects_phone_fields(client, path, payload, monkeypatch):
    from app.services.email_service import email_service
    from unittest.mock import Mock
    send = Mock()
    monkeypatch.setattr(email_service, "send_otp", send)
    assert client.post(path, json=payload).status_code == 422
    send.assert_not_called()


def test_api_schemas_and_user_model_have_no_phone_field(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ["RegisterRequest", "SendOtpRequest", "VerifyOtpRequest", "StudentRegisterRequest",
                 "StudentLoginRequest", "UpdateProfileRequest", "UserResponse"]:
        assert "phone" not in schemas[name]["properties"]
    assert "phone" not in User.__table__.columns


def test_profile_updates_reject_phone(client, test_user):
    from tests.conftest import get_auth_token
    token = get_auth_token(client, test_user)
    response = client.put("/api/auth/me", headers={"Authorization": f"Bearer {token}"},
                          json={"phone": "9876543210"})
    assert response.status_code == 422
    profile = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert profile.status_code == 200
    assert "phone" not in profile.json()
