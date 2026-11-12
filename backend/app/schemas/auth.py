from datetime import datetime
import re
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.db.models.user import UserRole

# Type alias for backward compatibility
EmailStr = str

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$")

def validate_email_address(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Email must be a string")
    value = value.strip().lower()
    if not value or len(value) > 254:
        raise ValueError("Email length must be between 1 and 254 characters")

    from app.config.settings import settings

    # 1. Allow configured admin email (e.g. achupporihelpdesk@gmail.com)
    admin_email = (getattr(settings, "ADMIN_EMAIL", "") or "").strip().lower()
    if admin_email and value == admin_email:
        if not EMAIL_REGEX.match(value):
            raise ValueError("value is not a valid email address")
        return value

    # 2. Allow test fixture / local mock domains (must still be a syntactically valid email)
    test_domains = (".local", "@example.com", "@example.invalid", "@campus.edu", "@university.edu")
    if settings.ENVIRONMENT.lower() not in ("production", "prod") and any(value.endswith(d) for d in test_domains):
        if not EMAIL_REGEX.match(value):
            raise ValueError("value is not a valid email address")
        return value

    # 3. Syntactic email validation
    try:
        from email_validator import validate_email, EmailNotValidError
        validated = validate_email(value, check_deliverability=False)
        value = validated.normalized
    except ImportError:
        pass
    except Exception as e:
        raise ValueError(str(e))

    if not EMAIL_REGEX.match(value):
        raise ValueError("value is not a valid email address")

    # 4. Enforce institutional domain restriction
    raw_domains = getattr(settings, "ALLOWED_STUDENT_EMAIL_DOMAINS", ["nec.edu.in"])
    if isinstance(raw_domains, str):
        allowed_domains = [d.strip().lower().lstrip("@") for d in raw_domains.split(",") if d.strip()]
    else:
        allowed_domains = [d.strip().lower().lstrip("@") for d in raw_domains if d.strip()]

    domain = value.split("@")[-1]
    if domain not in allowed_domains:
        domain_str = ", @".join(allowed_domains)
        raise ValueError(f"Registration and login are restricted to institutional emails ending with @{domain_str}.")

    return value

class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., max_length=254)
    password: str = Field(min_length=12, max_length=1024)
    otp: str = Field(pattern=r"^[0-9]{6}$")
    full_name: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_register_email(cls, value: str) -> str:
        return validate_email_address(value)

class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_login_email(cls, value: str) -> str:
        return validate_email_address(value)

class SendOtpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., max_length=254, description="User email address")
    purpose: Optional[str] = Field("login", description="Purpose: 'login' or 'signup'")

    @field_validator("email")
    @classmethod
    def validate_send_otp_email(cls, value: str) -> str:
        return validate_email_address(value)

class VerifyOtpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., max_length=254, description="User email address")
    otp: str = Field(..., min_length=4, max_length=8)

    @field_validator("email")
    @classmethod
    def validate_verify_otp_email(cls, value: str) -> str:
        return validate_email_address(value)

class StudentRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(..., min_length=2, max_length=100)
    roll_number: str = Field(..., min_length=2, max_length=50)
    email: str = Field(..., min_length=5, max_length=254)
    department: str = Field(..., min_length=2, max_length=100)
    otp: str = Field(..., min_length=4, max_length=8)

    @field_validator("email")
    @classmethod
    def validate_student_reg_email(cls, value: str) -> str:
        return validate_email_address(value)

class StudentLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., max_length=254, description="Student email address")
    otp: str = Field(..., min_length=4, max_length=8)

    @field_validator("email")
    @classmethod
    def validate_student_login_email(cls, value: str) -> str:
        return validate_email_address(value)

class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: Optional[str] = Field(default=None, max_length=100)
    department: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = None
    email_otp: Optional[str] = Field(default=None, pattern=r"^[0-9]{6}$")

    @field_validator("email")
    @classmethod
    def validate_update_email(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value.strip():
            return validate_email_address(value)
        return value

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: Optional["UserResponse"] = None

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: Optional[str] = None
    full_name: Optional[str] = None
    roll_number: Optional[str] = None
    department: Optional[str] = None
    role: UserRole
    is_active: bool
    created_at: datetime
