from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.conversation import ConversationType
from app.schemas.users import UserSearchResult


class DirectConversationRequest(BaseModel):
    target_user_id: int = Field(gt=0)


class DirectConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_type: ConversationType
    name: str | None
    created_at: datetime
    members: list[UserSearchResult]
