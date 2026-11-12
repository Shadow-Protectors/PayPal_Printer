"""Ownership checks for both signed-in customers and anonymous session holders."""
import hmac
import re
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.config.security import decode_token
from app.config.security import hash_token
from app.db.models.revoked_session import RevokedSession
from app.db.models.order import Order
from app.db.models.document import Document
from app.db.models.user import User, UserRole
from app.utils.errors import AppException


def identity(request: Request, db: Session):
    authorization = request.headers.get("authorization", "")
    bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    session = request.headers.get("x-customer-session", "").strip() or bearer
    if len(session) > 512:
        raise AppException(422, "VALIDATION_ERROR", "Invalid customer session.")
    payload = decode_token(bearer) if bearer else None
    if session and session != bearer and not re.fullmatch(r"sess_[A-Za-z0-9_-]{16,128}", session):
        raise AppException(422, "VALIDATION_ERROR", "Invalid customer session format.")
    if bearer.startswith('sess_') and not re.fullmatch(r"sess_[A-Za-z0-9_-]{16,128}", bearer):
        raise AppException(422, "VALIDATION_ERROR", "Invalid customer session format.")
    user = None
    if payload and payload.get("type") == "access":
        try:
            user = db.get(User, int(payload["sub"]))
        except (KeyError, ValueError, TypeError):
            pass
        if user and not user.is_active:
            user = None
        if user and user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN) and payload.get('role') not in ('ADMIN', 'SUPER_ADMIN'):
            raise AppException(401, 'ADMIN_SIGN_IN_REQUIRED', 'Sign in again with administrator credentials.')
    if bearer and not bearer.startswith("sess_") and not user:
        raise AppException(401, "UNAUTHENTICATED", "Invalid or inactive customer account.")
    if not session and not user:
        raise AppException(401, "UNAUTHENTICATED", "Start a customer session to continue.")
    if session and db.get(RevokedSession, hash_token(session)):
        raise AppException(401, "SESSION_REVOKED", "This customer session has ended.")
    return session, user


def check_owner(resource, session, user):
    if resource is None:
        raise AppException(404, "NOT_FOUND", "Record not found.")
    if user and (resource.user_id == user.id or user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)):
        return
    owner_session = (resource.print_settings or {}).get("session_token") if isinstance(resource, Order) else resource.session_token
    if owner_session and session and hmac.compare_digest(owner_session, session):
        return
    raise AppException(404, "NOT_FOUND", "Record not found for this customer.")


async def customer_access(request: Request, db: Session = Depends(get_db)):
    session, user = identity(request, db)
    order_id = request.path_params.get("order_id") or request.query_params.get("order_id")
    document_id = request.path_params.get("document_id")
    route_path = getattr(request.scope.get("route"), "path", request.url.path)
    if request.method == "POST" and route_path != "/api/documents/upload":
        raw_body = await request.body()
        if not raw_body:
            payload = {}
        else:
            try:
                payload = await request.json()
            except ValueError:
                raise AppException(422, "VALIDATION_ERROR", "Invalid JSON request body.")
        if isinstance(payload, dict):
            order_id = order_id or payload.get("orderId") or payload.get("order_id")
            doc_ids = [payload.get("documentId") or payload.get("document_id")]
            doc_ids += [item.get("documentId") or item.get("document_id") for item in (payload.get("items") or []) if isinstance(item, dict)]
            for doc_id in doc_ids:
                if doc_id:
                    if not isinstance(doc_id, str):
                        raise AppException(422, "VALIDATION_ERROR", "Invalid document identifier.")
                    check_owner(db.get(Document, doc_id), session, user)
    if order_id:
        if not isinstance(order_id, str):
            raise AppException(422, "VALIDATION_ERROR", "Invalid order identifier.")
        check_owner(db.get(Order, order_id), session, user)
    if document_id:
        check_owner(db.get(Document, document_id), session, user)
