import secrets
import hashlib
import base64
from cryptography.fernet import Fernet
from app.config.settings import settings

def _get_fernet() -> Fernet:
    # Derive a 32-byte key from JWT_SECRET_KEY
    key_bytes = hashlib.sha256(settings.JWT_SECRET_KEY.encode('utf-8')).digest()
    b64_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(b64_key)

def encrypt_value(plain_text: str) -> str:
    """Encrypts sensitive short string value."""
    fernet = _get_fernet()
    return fernet.encrypt(plain_text.encode('utf-8')).decode('utf-8')

def decrypt_value(cipher_text: str) -> str:
    """Decrypts cipher text."""
    fernet = _get_fernet()
    return fernet.decrypt(cipher_text.encode('utf-8')).decode('utf-8')

def generate_secure_otp(length: int = 6) -> str:
    """Generates a cryptographically secure numeric OTP."""
    digits = "0123456789"
    return "".join(secrets.choice(digits) for _ in range(length))

def hash_sha256(data: str | bytes) -> str:
    """Computes SHA-256 hash of a string or byte sequence."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()

def compute_file_sha256(file_path: str) -> str:
    """Computes SHA-256 hash of a file on disk in chunks."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()
