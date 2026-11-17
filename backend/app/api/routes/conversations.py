from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models import Conversation, User
from app.schemas.conversations import (
    DirectConversationRequest,
    DirectConversationResponse,
)
from app.schemas.users import UserSearchResult
from app.services.conversations import (
    SelfConversationError,
    TargetUserNotFoundError,
    start_or_get_direct_conversation,
)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


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
