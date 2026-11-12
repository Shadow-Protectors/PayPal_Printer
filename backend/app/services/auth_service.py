import secrets
import uuid
import threading
import hmac
from functools import wraps
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Dict, Any
from sqlalchemy.orm import Session
from fastapi import status
from app.services.email_service import email_service

from app.config.settings import settings
from app.config.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    hash_token,
    decode_token,
)
from app.db.models.user import User, UserRole
from app.db.models.refresh_token import RefreshToken
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    StudentRegisterRequest,
    StudentLoginRequest,
    UpdateProfileRequest,
)
from app.utils.errors import AppException

_email_lock = threading.RLock()


def serialized_email_operation(function):
    @wraps(function)
    def locked(*args, **kwargs):
        with _email_lock:
            return function(*args, **kwargs)
    return locked

class AuthService:
    @staticmethod
    def register(db: Session, req: RegisterRequest) -> User:
        AuthService.verify_email_otp(req.email, req.otp, purpose="signup")
        existing = db.query(User).filter(User.email == req.email.lower()).first()
        if existing:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="EMAIL_EXISTS",
                message="A user with this email address already exists."
            )

        user = User(
            email=req.email.lower(),
            full_name=req.full_name,
            password_hash=hash_password(req.password),
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    _email_otps: Dict[str, Dict[str, Any]] = {}

    @classmethod
    @serialized_email_operation
    def send_email_otp(cls, db: Session, email: str, purpose: str = "login") -> str:
        clean_email = email.strip().lower()
        clean_purpose = (purpose or "login").lower().strip()
        if clean_purpose not in {"login", "signup"}:
            raise AppException(422, "VALIDATION_ERROR", "Invalid verification purpose.")
        now = datetime.now(timezone.utc)
        for key, value in list(cls._email_otps.items()):
            if now - value.get("window_start", now) > timedelta(minutes=5):
                cls._email_otps.pop(key, None)
        if len(cls._email_otps) >= 10000 and clean_email not in cls._email_otps:
            raise AppException(429, "RATE_LIMIT_EXCEEDED", "Please try again later.")

        # Check existing user registration status
        existing_user = db.query(User).filter(User.email == clean_email).first()

        if clean_purpose == "login":
            if not existing_user:
                raise AppException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    error_code="USER_NOT_FOUND",
                    message="No account found with this email address. Please sign up first."
                )
            if not existing_user.is_active:
                raise AppException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    error_code="USER_INACTIVE",
                    message="Account has been deactivated. Please contact your administrator."
                )
            if existing_user.role != UserRole.USER:
                raise AppException(403, "ADMIN_PASSWORD_REQUIRED", "Use administrator password sign-in.")
        elif clean_purpose == "signup":
            if existing_user:
                raise AppException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_code="EMAIL_EXISTS",
                    message="An account with this email address already exists. Please sign in."
                )

        now = datetime.now(timezone.utc)
        record = cls._email_otps.get(clean_email)

        # Rate limit: max 3 requests within 5 minutes per email
        if record:
            window_start = record.get("window_start", now)
            if now - window_start < timedelta(minutes=5):
                if record.get("request_count", 0) >= 3:
                    raise AppException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        error_code="RATE_LIMIT_EXCEEDED",
                        message="Too many verification requests. Please wait a few minutes before trying again."
                    )
                record["request_count"] = record.get("request_count", 0) + 1
            else:
                record["window_start"] = now
                record["request_count"] = 1
        else:
            record = {"window_start": now, "request_count": 1}

        # Cryptographically secure 6-digit OTP
        otp = f"{secrets.randbelow(900000) + 100000}"
        record["otp"] = otp
        record["purpose"] = clean_purpose
        record["expires_at"] = now + timedelta(minutes=5)
        record["attempts"] = 0
        cls._email_otps[clean_email] = record

        # Dispatch via Gmail SMTP
        if not email_service.send_otp(clean_email, otp, clean_purpose):
            record.pop("otp", None)
            raise AppException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error_code="EMAIL_DELIVERY_FAILED",
                message="Could not send the verification email. Please try again shortly."
            )
        return otp

    @classmethod
    @serialized_email_operation
    def verify_email_otp(cls, email: str, otp: str, consume: bool = True, purpose: str = None) -> bool:
        clean_email = email.strip().lower()
        clean_otp = str(otp).strip()

        record = cls._email_otps.get(clean_email)
        if not record:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="OTP_NOT_FOUND",
                message="No verification code was requested for this email."
            )

        now = datetime.now(timezone.utc)
        if now > record.get("expires_at", now):
            cls._email_otps.pop(clean_email, None)
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="OTP_EXPIRED",
                message="The verification code has expired. Please request a new code."
            )

        if record.get("attempts", 0) >= 3:
            cls._email_otps.pop(clean_email, None)
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="MAX_ATTEMPTS_EXCEEDED",
                message="Maximum verification attempts exceeded. Please request a new code."
            )

        if (not hmac.compare_digest(str(record.get("otp", "")), clean_otp) or
                (purpose is not None and record.get("purpose") != purpose)):
            record["attempts"] = record.get("attempts", 0) + 1
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="INVALID_OTP",
                message="Invalid verification code."
            )

        if consume:
            cls._email_otps.pop(clean_email, None)
        else:
            record["verified"] = True
        return True

    @staticmethod
    def _issue_tokens(db: Session, user: User) -> Tuple[User, str, str, int]:
        is_admin = user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)

        # Admin sessions: 6 h access token + 1 day refresh (shorter, safer).
        # Student sessions: 60 min access token + 30 day refresh.
        if is_admin:
            access_expire = timedelta(minutes=settings.JWT_ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES)
            refresh_expire_days = settings.JWT_ADMIN_REFRESH_TOKEN_EXPIRE_DAYS
        else:
            access_expire = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
            refresh_expire_days = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS

        token_data = {"sub": str(user.id), "role": user.role.value, "jti": uuid.uuid4().hex}
        access_token = create_access_token(token_data, expires_delta=access_expire)
        refresh_token = create_refresh_token(token_data, expires_delta=timedelta(days=refresh_expire_days))

        hashed_refresh = hash_token(refresh_token)
        expires_at = datetime.now(timezone.utc) + timedelta(days=refresh_expire_days)

        db_refresh = RefreshToken(
            user_id=user.id,
            token_hash=hashed_refresh,
            expires_at=expires_at,
            revoked=False
        )
        db.add(db_refresh)
        db.commit()

        expires_in = int(access_expire.total_seconds())
        return user, access_token, refresh_token, expires_in

    @classmethod
    @serialized_email_operation
    def student_register(
        cls,
        db: Session,
        req: "StudentRegisterRequest"
    ) -> Tuple[User, str, str, int]:
        clean_email = req.email.strip().lower()
        clean_roll = req.roll_number.strip().upper()

        if db.query(User).filter(User.email == clean_email).first():
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="EMAIL_EXISTS",
                message="An account with this email already exists. Please sign in."
            )

        if db.query(User).filter(User.roll_number == clean_roll).first():
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="ROLL_EXISTS",
                message="An account with this roll number already exists."
            )

        cls.verify_email_otp(clean_email, req.otp, consume=False, purpose="signup")

        # Resolve department ID and canonical name if department exists in catalog
        dept_id = None
        dept_name_resolved = req.department.strip() if req.department else None
        if req.department:
            from app.db.models.department import Department
            dept_text = req.department.strip()
            dept_match = db.query(Department).filter(
                (Department.name.ilike(dept_text)) | 
                (Department.code.ilike(dept_text)) |
                (Department.name.ilike(f"%{dept_text}%"))
            ).first()
            if not dept_match:
                import re
                code_match = re.search(r'\(([^)]+)\)', dept_text)
                if code_match:
                    code_extracted = code_match.group(1).strip()
                    dept_match = db.query(Department).filter(
                        (Department.code.ilike(code_extracted)) |
                        (Department.name.ilike(f"%{code_extracted}%"))
                    ).first()
            if dept_match:
                dept_id = dept_match.id
                dept_name_resolved = dept_match.name

        user = User(
            email=clean_email,
            roll_number=clean_roll,
            full_name=req.full_name.strip(),
            department=dept_name_resolved,
            department_id=dept_id,
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()
            raise

        # User is securely persisted in the database; now consume the one-time verification code
        cls._email_otps.pop(clean_email, None)

        return cls._issue_tokens(db, user)

    @classmethod
    @serialized_email_operation
    def student_login(
        cls,
        db: Session,
        req: "StudentLoginRequest"
    ) -> Tuple[User, str, str, int]:
        target_email = req.email.strip().lower()
        if not target_email:
            raise AppException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_code="EMAIL_REQUIRED",
                message="Email address is required."
            )

        cls.verify_email_otp(target_email, req.otp, consume=False, purpose="login")

        user = db.query(User).filter(User.email == target_email).first()
        if not user:
            raise AppException(
                status_code=status.HTTP_404_NOT_FOUND,
                error_code="USER_NOT_FOUND",
                message="No account found with this email. Please sign up first."
            )

        if not user.is_active:
            raise AppException(
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="USER_INACTIVE",
                message="Account has been deactivated."
            )

        if user.role != UserRole.USER:
            raise AppException(403, "ADMIN_PASSWORD_REQUIRED", "Use administrator password sign-in.")

        res = cls._issue_tokens(db, user)
        # Authentication succeeded; consume OTP
        cls._email_otps.pop(target_email, None)
        return res

    @staticmethod
    def update_profile(
        db: Session,
        user: User,
        req: "UpdateProfileRequest"
    ) -> User:
        if req.full_name is not None and req.full_name.strip():
            user.full_name = req.full_name.strip()
        if req.department is not None and req.department.strip():
            dept_text = req.department.strip()
            user.department = dept_text
            from app.db.models.department import Department
            dept_match = db.query(Department).filter(
                (Department.name.ilike(dept_text)) | 
                (Department.code.ilike(dept_text)) |
                (Department.name.ilike(f"%{dept_text}%"))
            ).first()
            if not dept_match:
                import re
                code_match = re.search(r'\(([^)]+)\)', dept_text)
                if code_match:
                    code_extracted = code_match.group(1).strip()
                    dept_match = db.query(Department).filter(
                        (Department.code.ilike(code_extracted)) |
                        (Department.name.ilike(f"%{code_extracted}%"))
                    ).first()
            if dept_match:
                user.department_id = dept_match.id
                user.department = dept_match.name
        if req.email is not None and req.email.strip() and req.email.strip().lower() != (user.email or "").lower():
            clean_email = req.email.strip().lower()
            cls_otp = req.email_otp
            AuthService.verify_email_otp(clean_email, cls_otp or "", purpose="signup")
            existing = db.query(User).filter(User.email == clean_email, User.id != user.id).first()
            if existing:
                raise AppException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_code="EMAIL_EXISTS",
                    message="This email is already associated with another account."
                )
            user.email = clean_email
        db.commit()
        db.refresh(user)
        return user

    @classmethod
    def login(cls, db: Session, req: LoginRequest, admin_only: bool = False) -> Tuple[User, str, str, int]:
        user = db.query(User).filter(User.email == req.email.lower()).first()
        if not user or not user.password_hash or not verify_password(req.password, user.password_hash):
            raise AppException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_code="UNAUTHENTICATED",
                message="Invalid email or password."
            )

        if not user.is_active:
            raise AppException(
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="USER_INACTIVE",
                message="Account has been deactivated."
            )

        if admin_only and user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            raise AppException(
                status_code=status.HTTP_403_FORBIDDEN,
                error_code="FORBIDDEN",
                message="Administrator privileges required."
            )

        return cls._issue_tokens(db, user)

    @staticmethod
    def refresh_access_token(db: Session, refresh_token_str: str) -> Tuple[str, int]:
        payload = decode_token(refresh_token_str)
        if not payload or payload.get("type") != "refresh":
            raise AppException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_code="INVALID_TOKEN",
                message="Invalid or expired refresh token."
            )

        hashed_token = hash_token(refresh_token_str)
        db_token = db.query(RefreshToken).filter(
            RefreshToken.token_hash == hashed_token,
            RefreshToken.revoked == False
        ).first()

        if not db_token:
            raise AppException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_code="INVALID_TOKEN",
                message="Refresh token has been revoked or is invalid."
            )

        # Compare dates with timezone awareness
        db_token_expires = db_token.expires_at
        if db_token_expires.tzinfo is None:
            db_token_expires = db_token_expires.replace(tzinfo=timezone.utc)

        if db_token_expires < datetime.now(timezone.utc):
            raise AppException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_code="TOKEN_EXPIRED",
                message="Refresh token has expired."
            )

        user = db.query(User).filter(User.id == db_token.user_id).first()
        if not user or not user.is_active:
            raise AppException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_code="UNAUTHENTICATED",
                message="User not found or inactive."
            )

        is_admin = user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)
        if is_admin:
            access_expire = timedelta(minutes=settings.JWT_ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES)
        else:
            access_expire = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        new_access_token = create_access_token(
            {"sub": str(user.id), "role": user.role.value},
            expires_delta=access_expire
        )
        expires_in = int(access_expire.total_seconds())
        return new_access_token, expires_in

    @staticmethod
    def logout(db: Session, refresh_token_str: str):
        hashed_token = hash_token(refresh_token_str)
        db_token = db.query(RefreshToken).filter(RefreshToken.token_hash == hashed_token).first()
        if db_token:
            db_token.revoked = True
            db.commit()

auth_service = AuthService()
