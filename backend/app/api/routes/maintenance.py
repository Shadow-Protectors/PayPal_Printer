from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.api.dependencies import get_current_admin
from app.services.cleanup_service import cleanup_service

router = APIRouter(prefix="/api/maintenance", tags=["Maintenance"])

@router.post("/cleanup")
def trigger_storage_cleanup(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    return cleanup_service.run_storage_cleanup(db)
