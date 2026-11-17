from typing import Literal

from pydantic import BaseModel, ConfigDict


class WebSocketMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["message.send"]
    content: str
