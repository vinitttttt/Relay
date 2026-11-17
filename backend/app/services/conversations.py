from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, selectinload

from app.models import Conversation, ConversationMember, ConversationType, User


class SelfConversationError(Exception):
    """Raised when a user tries to start a direct conversation with themself."""


class TargetUserNotFoundError(Exception):
    """Raised when the requested conversation participant does not exist."""


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
    )
    session.add(conversation)
    session.add_all(
        [
            ConversationMember(
                conversation=conversation,
                user_id=current_user_id,
            ),
            ConversationMember(
                conversation=conversation,
                user_id=target_user_id,
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
