import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.api.customer_access import identity
from app.config.security import hash_token
from app.db.models.revoked_session import RevokedSession

router = APIRouter(prefix="/api/sessions", tags=["Customer Sessions"])

@router.post("", status_code=201)
def start_session():
    """Provides a customer session token for frontend state and rate tracking."""
    return {
        "token": f"sess_{uuid.uuid4().hex}",
        "expiresAt": None,
    }

@router.delete("/current")
def end_session(request: Request, db: Session = Depends(get_db)):
    """Revokes current customer session."""
    session, user = identity(request, db)
    if session:
        token_hash = hash_token(session)
        if not db.get(RevokedSession, token_hash):
            db.add(RevokedSession(token_hash=token_hash))
            db.commit()
    return {"status": "ended"}
