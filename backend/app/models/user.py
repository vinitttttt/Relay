from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.core.time import utc_now


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    memberships: Mapped[list["ConversationMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sent_messages: Mapped[list["Message"]] = relationship(back_populates="sender")
