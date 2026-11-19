from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.core.time import utc_now


class ConversationMember(Base):
    __tablename__ = "conversation_members"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "user_id", name="uq_conversation_members_pair"
        ),
        Index("ix_conversation_members_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")
