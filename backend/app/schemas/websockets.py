from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WebSocketMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["message.send"]
    client_message_id: str = Field(min_length=1, max_length=100)
    content: str
