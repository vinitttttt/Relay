import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ConversationType(str, enum.Enum):
    DIRECT = "direct"
    GROUP = "group"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_created_at", "created_at"),
        Index(
            "uq_conversations_direct_user_pair",
            "direct_user_low_id",
            "direct_user_high_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_type: Mapped[ConversationType] = mapped_column(
        Enum(
            ConversationType,
            name="ck_conversations_conversation_type",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Canonical pair keys support the unique index; membership rows retain user FKs.
    direct_user_low_id: Mapped[int | None] = mapped_column(nullable=True)
    direct_user_high_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    members: Mapped[list["ConversationMember"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
