from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content cannot be empty or whitespace.")
        return value


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    content: str
    created_at: datetime
    sender: UserSearchResult


class ConversationListItem(BaseModel):
    id: int
    conversation_type: ConversationType
    name: str | None
    created_at: datetime
    members: list[UserSearchResult]
    latest_message: MessageResponse | None


class ConversationMessagePage(BaseModel):
    items: list[MessageResponse]
    next_cursor: int | None
