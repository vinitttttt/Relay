from fastapi import APIRouter, HTTPException

from app.db.session import database_is_available

router = APIRouter(tags=["health"])


@router.get("/health/database")
def database_health_check() -> dict[str, str]:
    """Report PostgreSQL connectivity without exposing connection details."""
    if not database_is_available():
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok"}
