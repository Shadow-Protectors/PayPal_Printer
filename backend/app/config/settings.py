import os
import json
from pathlib import Path
from typing import List, Union
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str = "Achuppori"
    ENVIRONMENT: str = "development"
    ROOT_PATH: str = "/achuppori"
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    DATABASE_URL: str = "sqlite:///./print_platform.db"

    # Auth & Tokens
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30         # student refresh token: 30 days

    # Admin sessions are intentionally shorter to limit blast radius of a stolen token.
    JWT_ADMIN_ACCESS_TOKEN_EXPIRE_MINUTES: int = 360   # 6 hours
    JWT_ADMIN_REFRESH_TOKEN_EXPIRE_DAYS: int = 1       # 1 day

    STORAGE_ROOT: str = "./storage"
    MAX_UPLOAD_MB: int = 50

    # OTP Configuration & Rate Limiting
    OTP_TTL_MINUTES: int = 30
    MAX_OTP_ATTEMPTS: int = 5
    MAX_PRINT_RETRIES: int = 2
    OTP_COOLDOWN_SECONDS: int = 60
    OTP_RATE_LIMIT_ATTEMPTS: int = 10
    OTP_RATE_LIMIT_WINDOW_SECONDS: int = 60

    PER_PAGE_RATE: float = 2.00
    BASE_FEE: float = 0.00

    # Email Configuration for Student Email OTP (Gmail SMTP)
    EMAIL_PROVIDER: str = "smtp"  # "smtp", "mock"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "Achuppori Cloud Print"
    ENABLE_EMAIL_STATUS_NOTIFICATIONS: bool = True
    REPORT_PRINCIPAL_EMAIL: str = ""
    REPORT_ACCOUNTS_EMAIL: str = ""
    REPORT_SYSADMIN_EMAIL: str = ""
    REPORT_DEPARTMENT_EMAILS: dict[str, str] = {}


    # Razorpay Secrets (Loaded strictly from environment variables)
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    # CORS Allowed Origins
    ALLOWED_ORIGINS: Union[List[str], str] = ["https://nec.edu.in"]

    HEARTBEAT_TIMEOUT_SECONDS: int = 120

    # Initial Admin & Seed Credentials (loaded from .env)
    ALLOWED_STUDENT_EMAIL_DOMAINS: Union[List[str], str] = ["nec.edu.in"]
    ADMIN_EMAIL: str = "achupporihelpdesk@gmail.com"
    ADMIN_PASSWORD: str = ""
    ADMIN_NAME: str = "Platform Administrator"
    INTERNAL_AGENT_TOKEN: str = ""
    DEFAULT_PRINT_SERVER_ID: str = ""
    DEFAULT_PRINT_SERVER_NAME: str = "Central Library Station"
    DEFAULT_PRINT_SERVER_LOCATION: str = "Main Campus Library Floor 1"

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @model_validator(mode="after")
    def validate_and_normalize_settings(self) -> "Settings":
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        if self.DATABASE_URL.startswith("sqlite:///./"):
            db_name = self.DATABASE_URL.replace("sqlite:///./", "")
            self.DATABASE_URL = f"sqlite:///{(project_root / db_name).resolve()}"
        if self.STORAGE_ROOT.startswith("./"):
            self.STORAGE_ROOT = str((project_root / self.STORAGE_ROOT[2:]).resolve())

        # Normalize ALLOWED_ORIGINS to list if string
        if isinstance(self.ALLOWED_ORIGINS, str):
            try:
                parsed = json.loads(self.ALLOWED_ORIGINS)
                if isinstance(parsed, list):
                    self.ALLOWED_ORIGINS = parsed
                else:
                    self.ALLOWED_ORIGINS = [s.strip() for s in self.ALLOWED_ORIGINS.split(",") if s.strip()]
            except Exception:
                self.ALLOWED_ORIGINS = [s.strip() for s in self.ALLOWED_ORIGINS.split(",") if s.strip()]

        # Normalize ALLOWED_STUDENT_EMAIL_DOMAINS
        if isinstance(self.ALLOWED_STUDENT_EMAIL_DOMAINS, str):
            try:
                parsed = json.loads(self.ALLOWED_STUDENT_EMAIL_DOMAINS)
                if isinstance(parsed, list):
                    self.ALLOWED_STUDENT_EMAIL_DOMAINS = [d.strip().lower().lstrip("@") for d in parsed if d.strip()]
                else:
                    self.ALLOWED_STUDENT_EMAIL_DOMAINS = [s.strip().lower().lstrip("@") for s in self.ALLOWED_STUDENT_EMAIL_DOMAINS.split(",") if s.strip()]
            except Exception:
                self.ALLOWED_STUDENT_EMAIL_DOMAINS = [s.strip().lower().lstrip("@") for s in self.ALLOWED_STUDENT_EMAIL_DOMAINS.split(",") if s.strip()]
        elif isinstance(self.ALLOWED_STUDENT_EMAIL_DOMAINS, list):
            self.ALLOWED_STUDENT_EMAIL_DOMAINS = [d.strip().lower().lstrip("@") for d in self.ALLOWED_STUDENT_EMAIL_DOMAINS if d.strip()]

        is_prod = self.ENVIRONMENT.lower() in ("production", "prod")
        if self.EMAIL_PROVIDER not in {"smtp", "mock"}:
            raise RuntimeError("EMAIL_PROVIDER must be smtp or mock.")
        if is_prod and self.EMAIL_PROVIDER != "smtp":
            raise RuntimeError("Production requires SMTP; mock email delivery is for isolated development only.")
        insecure_keys = {
            "CHANGE_ME_SUPER_SECRET_KEY_AT_LEAST_32_CHARS",
            "secret",
            "changeme",
            "default",
            "",
        }

        if is_prod:
            missing_secrets = []
            if len(self.JWT_SECRET_KEY) < 32 or self.JWT_SECRET_KEY in insecure_keys:
                missing_secrets.append("JWT_SECRET_KEY (must be strong, non-default secret in production)")
            if not self.DATABASE_URL:
                missing_secrets.append("DATABASE_URL")
            if missing_secrets:
                raise RuntimeError(
                    f"CRITICAL SECURITY CONFIGURATION ERROR: The following required production secrets are missing or insecure: {', '.join(missing_secrets)}. "
                    f"Configure them via environment variables or .env file before starting in production mode."
                )
        return self

settings = Settings()
