from pydantic import BaseModel, ConfigDict


class UserSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
