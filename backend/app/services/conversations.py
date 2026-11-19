from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, selectinload

from app.models import Conversation, ConversationMember, ConversationType, Message, User
from app.core.time import utc_now


class SelfConversationError(Exception):
    """Raised when a user tries to start a direct conversation with themself."""


class TargetUserNotFoundError(Exception):
    """Raised when the requested conversation participant does not exist."""


class ConversationAccessError(Exception):
    """Raised when a user is not a member of the requested conversation."""


class AuthenticationExpiredError(Exception):
    """Raised when a WebSocket session expires before message commit."""


class MessageIdempotencyConflictError(Exception):
    """Raised when a client message ID is retried with different content."""


def get_conversation_user(
    session: Session, conversation_id: int, user_id: int
) -> User:
    user = session.scalar(
        select(User)
        .join(ConversationMember, ConversationMember.user_id == User.id)
        .where(
            ConversationMember.conversation_id == conversation_id,
            User.id == user_id,
        )
    )
    if user is None:
        raise ConversationAccessError
    return user


def list_user_conversations(session: Session, user_id: int):
    latest = (
        select(
            Message.id.label("message_id"),
            Message.conversation_id.label("conversation_id"),
            func.row_number()
            .over(
                partition_by=Message.conversation_id,
                order_by=(Message.created_at.desc(), Message.id.desc()),
            )
            .label("position"),
        )
        .subquery()
    )
    latest_message_id = (
        select(latest.c.message_id)
        .where(latest.c.conversation_id == Conversation.id, latest.c.position == 1)
        .scalar_subquery()
    )
    latest_time = select(Message.created_at).where(Message.id == latest_message_id).scalar_subquery()
    conversations = session.scalars(
        select(Conversation)
        .join(ConversationMember)
        .where(ConversationMember.user_id == user_id)
        .options(
            selectinload(Conversation.members).selectinload(ConversationMember.user)
        )
        .order_by(func.coalesce(latest_time, Conversation.created_at).desc(), Conversation.id.desc())
    ).all()
    conversation_ids = [conversation.id for conversation in conversations]
    latest_messages = session.scalars(
        select(Message).where(
            Message.id.in_(
                select(latest.c.message_id).where(
                    latest.c.position == 1,
                    latest.c.conversation_id.in_(conversation_ids),
                )
            )
        )
        .options(selectinload(Message.sender))
    ).all() if conversation_ids else []
    return conversations, {message.conversation_id: message for message in latest_messages}


def _require_membership(session: Session, conversation_id: int, user_id: int) -> None:
    is_member = session.scalar(
        select(ConversationMember.id).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    if is_member is None:
        raise ConversationAccessError


def create_message(
    session: Session,
    conversation_id: int,
    user: User,
    content: str,
    authentication_expires_at: datetime | None = None,
    client_message_id: str | None = None,
) -> tuple[Message, bool]:
    if authentication_expires_at is not None and datetime.now(timezone.utc) >= authentication_expires_at:
        raise AuthenticationExpiredError
    _require_membership(session, conversation_id, user.id)
    if client_message_id is not None:
        existing = session.scalar(
            select(Message).options(selectinload(Message.sender)).where(
                Message.conversation_id == conversation_id,
                Message.sender_id == user.id,
                Message.client_message_id == client_message_id,
            )
        )
        if existing is not None:
            if existing.content != content:
                raise MessageIdempotencyConflictError
            return existing, False
    if authentication_expires_at is not None and datetime.now(timezone.utc) >= authentication_expires_at:
        raise AuthenticationExpiredError
    message = Message(
        conversation_id=conversation_id,
        sender_id=user.id,
        content=content,
        client_message_id=client_message_id,
        created_at=utc_now(),
    )
    session.add(message)
    if authentication_expires_at is not None and datetime.now(timezone.utc) >= authentication_expires_at:
        session.rollback()
        raise AuthenticationExpiredError
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if client_message_id is None:
            raise
        existing = session.scalar(
            select(Message).options(selectinload(Message.sender)).where(
                Message.conversation_id == conversation_id,
                Message.sender_id == user.id,
                Message.client_message_id == client_message_id,
            )
        )
        if existing is None:
            raise
        if existing.content != content:
            raise MessageIdempotencyConflictError
        return existing, False
    session.refresh(message)
    return message, True


def get_message_page(
    session: Session,
    conversation_id: int,
    user_id: int,
    limit: int,
    before_id: int | None,
    after_id: int | None = None,
):
    _require_membership(session, conversation_id, user_id)
    statement = select(Message).where(Message.conversation_id == conversation_id)
    if before_id is not None:
        statement = statement.where(Message.id < before_id)
    if after_id is not None:
        statement = statement.where(Message.id > after_id)
        rows = session.scalars(
            statement.options(selectinload(Message.sender))
            .order_by(Message.id.asc())
            .limit(limit + 1)
        ).all()
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = page[-1].id if has_more and page else None
        return page, next_cursor
    rows = session.scalars(
        statement.options(selectinload(Message.sender))
        .order_by(Message.id.desc())
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    page = list(reversed(rows[:limit]))
    next_cursor = page[0].id if has_more and page else None
    return page, next_cursor


def _find_direct_conversation(
    session: Session,
    current_user_id: int,
    target_user_id: int,
    low_user_id: int,
    high_user_id: int,
) -> Conversation | None:
    current_member = aliased(ConversationMember)
    target_member = aliased(ConversationMember)
    return session.scalar(
        select(Conversation)
        .join(
            current_member,
            current_member.conversation_id == Conversation.id,
        )
        .join(
            target_member,
            target_member.conversation_id == Conversation.id,
        )
        .where(
            Conversation.conversation_type == ConversationType.DIRECT,
            Conversation.direct_user_low_id == low_user_id,
            Conversation.direct_user_high_id == high_user_id,
            current_member.user_id == current_user_id,
            target_member.user_id == target_user_id,
        )
        .options(
            selectinload(Conversation.members).selectinload(ConversationMember.user)
        )
        .limit(1)
    )


def start_or_get_direct_conversation(
    session: Session,
    current_user: User,
    target_user_id: int,
) -> tuple[Conversation, bool]:
    """Return the member's direct conversation or atomically create one."""
    current_user_id = current_user.id
    if current_user_id == target_user_id:
        raise SelfConversationError
    if session.get(User, target_user_id) is None:
        raise TargetUserNotFoundError

    low_user_id, high_user_id = sorted((current_user_id, target_user_id))
    existing = _find_direct_conversation(
        session,
        current_user_id,
        target_user_id,
        low_user_id,
        high_user_id,
    )
    if existing is not None:
        return existing, False

    conversation = Conversation(
        conversation_type=ConversationType.DIRECT,
        direct_user_low_id=low_user_id,
        direct_user_high_id=high_user_id,
        created_at=utc_now(),
    )
    session.add(conversation)
    session.add_all(
        [
            ConversationMember(
                conversation=conversation,
                user_id=current_user_id,
                joined_at=utc_now(),
            ),
            ConversationMember(
                conversation=conversation,
                user_id=target_user_id,
                joined_at=utc_now(),
            ),
        ]
    )

    try:
        # The conversation and both memberships are committed as one transaction.
        session.commit()
    except IntegrityError:
        # A simultaneous request may have inserted the same unique user pair.
        session.rollback()
        existing = _find_direct_conversation(
            session,
            current_user_id,
            target_user_id,
            low_user_id,
            high_user_id,
        )
        if existing is not None:
            return existing, False
        if session.get(User, target_user_id) is None:
            raise TargetUserNotFoundError
        raise

    existing = _find_direct_conversation(
        session,
        current_user_id,
        target_user_id,
        low_user_id,
        high_user_id,
    )
    if existing is None:
        raise RuntimeError("Created direct conversation could not be retrieved.")
    return existing, True
