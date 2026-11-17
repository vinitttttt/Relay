from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User

MAX_USER_SEARCH_RESULTS = 20


def search_users(session: Session, query: str, current_user_id: int) -> list[User]:
    """Find public user records by case-insensitive partial username."""
    escaped_query = (
        query.strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return list(
        session.scalars(
            select(User)
            .where(
                User.id != current_user_id,
                User.username.ilike(f"%{escaped_query}%", escape="\\"),
            )
            .order_by(func.lower(User.username), User.id)
            .limit(MAX_USER_SEARCH_RESULTS)
        ).all()
    )
