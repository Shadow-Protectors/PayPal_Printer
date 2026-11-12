from fastapi import APIRouter, Depends, status, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    UserResponse,
    SendOtpRequest,
    VerifyOtpRequest,
    StudentRegisterRequest,
    StudentLoginRequest,
    UpdateProfileRequest,
)
from app.schemas.common import MessageResponse
from app.services.auth_service import auth_service
from app.services.department_service import department_service
from app.schemas.department import PublicDepartmentItem
from typing import List
from app.config.settings import settings
from app.api.dependencies import get_current_user, get_current_admin

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


async def throttle_auth(request: Request):
    if request.method != "POST":
        return
    from app.utils.rate_limit import auth_limiter
    address = request.client.host if request.client else "unknown"
    # Never trust a caller-supplied forwarded IP here. Nginx/Uvicorn handle the
    # explicitly trusted proxy configuration before request.client is populated.
    auth_limiter.check(("auth-ip", address), 60, 60)
    if request.url.path.endswith(("/login", "/send-otp", "/verify-otp")):
        try:
            body = await request.json()
        except ValueError:
            return
        email = str(body.get("email", "")).strip().lower() if isinstance(body, dict) else ""
        if email:
            auth_limiter.check((request.url.path, email), 10, 300)


router.dependencies.append(Depends(throttle_auth))

@router.get("/departments", response_model=List[PublicDepartmentItem])
def get_auth_departments(db: Session = Depends(get_db)):
    """
    Returns configured departments from DB for unauthenticated student registration.
    """
    return department_service.get_public_departments(db)

@router.post("/send-otp")
def send_otp(req: SendOtpRequest, db: Session = Depends(get_db)):
    target = req.email.strip()
    if not target:
        from app.utils.errors import AppException
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="EMAIL_REQUIRED",
            message="Email address is required to send verification code."
        )
    auth_service.send_email_otp(db, target, req.purpose or "login")
    return {
        "message": "Verification code sent successfully to your email.",
        "email": target
    }

@router.post("/verify-otp")
def verify_otp(req: VerifyOtpRequest):
    target = req.email.strip()
    if not target:
        from app.utils.errors import AppException
        raise AppException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="EMAIL_REQUIRED",
            message="Email address is required."
        )
    auth_service.verify_email_otp(target, req.otp, consume=False)
    return {"message": "Verification code is valid.", "valid": True}

@router.post("/student/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def student_signup(req: StudentRegisterRequest, db: Session = Depends(get_db)):
    user, access_token, refresh_token, expires_in = auth_service.student_register(db, req)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )

@router.post("/student/login", response_model=TokenResponse)
def student_login(req: StudentLoginRequest, db: Session = Depends(get_db)):
    user, access_token, refresh_token, expires_in = auth_service.student_login(db, req)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(req: RegisterRequest, db: Session = Depends(get_db)):
    user = auth_service.register(db, req)
    return user

@router.post("/login", response_model=TokenResponse)
def login_user(req: LoginRequest, db: Session = Depends(get_db)):
    user, access_token, refresh_token, expires_in = auth_service.login(db, req)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )

@router.post("/refresh", response_model=TokenResponse)
def refresh_token(req: RefreshTokenRequest, db: Session = Depends(get_db)):
    new_access_token, expires_in = auth_service.refresh_access_token(db, req.refresh_token)
    return TokenResponse(
        access_token=new_access_token,
        refresh_token=req.refresh_token,
        token_type="Bearer",
        expires_in=expires_in
    )

@router.post("/logout", response_model=MessageResponse)
def logout_user(req: RefreshTokenRequest, db: Session = Depends(get_db)):
    auth_service.logout(db, req.refresh_token)
    return MessageResponse(message="Logged out successfully.")

@router.get("/me", response_model=UserResponse)
def get_current_user_profile(user: User = Depends(get_current_user)):
    return user

@router.put("/me", response_model=UserResponse)
def update_current_user_profile(
    req: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    updated = auth_service.update_profile(db, user, req)
    return updated

@router.post("/admin/login", response_model=TokenResponse)
def login_admin(req: LoginRequest, db: Session = Depends(get_db)):
    user, access_token, refresh_token, expires_in = auth_service.login(db, req, admin_only=True)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user)
    )

@router.get("/admin/me", response_model=UserResponse)
def get_admin_profile(user: User = Depends(get_current_admin)):
    return user
