from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import get_rate_limit, get_rate_limit_window_seconds
from app.core.rate_limit import check_rate_limit
from app.db.session import get_db
from app.models import User
from app.schemas.users import UserSearchResult
from app.services.users import search_users

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/search", response_model=list[UserSearchResult])
def search_users_endpoint(
    q: Annotated[str, Query(min_length=2, max_length=50)],
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[User]:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(
            status_code=422,
            detail="Search query must contain at least 2 characters.",
        )
    check_rate_limit(
        "user_search", str(current_user.id),
        get_rate_limit("USER_SEARCH", 60),
        get_rate_limit_window_seconds("USER_SEARCH", 60),
    )
    return search_users(session, query, current_user.id)
