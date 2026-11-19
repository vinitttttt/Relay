from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models import Conversation, User
from app.schemas.conversations import (
    DirectConversationRequest,
    DirectConversationResponse,
    ConversationListItem,
    ConversationMessagePage,
    MessageCreate,
    MessageResponse,
)
from app.schemas.users import UserSearchResult
from app.services.conversations import (
    SelfConversationError,
    TargetUserNotFoundError,
    ConversationAccessError,
    create_message,
    MessageIdempotencyConflictError,
    get_message_page,
    list_user_conversations,
    start_or_get_direct_conversation,
)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationListItem])
def get_conversations(
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ConversationListItem]:
    conversations, latest_messages = list_user_conversations(session, current_user.id)
    return [
        ConversationListItem(
            id=conversation.id,
            conversation_type=conversation.conversation_type,
            name=conversation.name,
            created_at=conversation.created_at,
            members=[
                UserSearchResult.model_validate(member.user)
                for member in sorted(conversation.members, key=lambda member: member.user_id)
            ],
            latest_message=(
                MessageResponse.model_validate(latest_messages[conversation.id])
                if conversation.id in latest_messages
                else None
            ),
        )
        for conversation in conversations
    ]


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    conversation_id: int,
    payload: MessageCreate,
    response: Response,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    try:
        message, created = create_message(
            session,
            conversation_id,
            current_user,
            payload.content,
            client_message_id=payload.client_message_id,
        )
    except ConversationAccessError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found.") from exc
    except MessageIdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="client_message_id was already used with different message content.",
        ) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    return MessageResponse.model_validate(message)


@router.get("/{conversation_id}/messages", response_model=ConversationMessagePage)
def get_messages(
    conversation_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    before_id: int | None = Query(default=None, gt=0),
    after_id: int | None = Query(default=None, ge=0),
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationMessagePage:
    if before_id is not None and after_id is not None:
        raise HTTPException(status_code=422, detail="Use either before_id or after_id, not both.")
    try:
        messages, next_cursor = get_message_page(
            session, conversation_id, current_user.id, limit, before_id, after_id
        )
    except ConversationAccessError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found.") from exc
    return ConversationMessagePage(
        items=[MessageResponse.model_validate(message) for message in messages],
        next_cursor=next_cursor,
    )


def _serialize_direct_conversation(
    conversation: Conversation,
) -> DirectConversationResponse:
    members = sorted(conversation.members, key=lambda member: member.user_id)
    return DirectConversationResponse(
        id=conversation.id,
        conversation_type=conversation.conversation_type,
        name=conversation.name,
        created_at=conversation.created_at,
        members=[UserSearchResult.model_validate(member.user) for member in members],
    )


@router.post(
    "/direct",
    response_model=DirectConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_direct_conversation(
    payload: DirectConversationRequest,
    response: Response,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DirectConversationResponse:
    try:
        conversation, created = start_or_get_direct_conversation(
            session,
            current_user,
            payload.target_user_id,
        )
    except SelfConversationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot start a direct conversation with yourself.",
        ) from exc
    except TargetUserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found.",
        ) from exc

    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return _serialize_direct_conversation(conversation)
