from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)


Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9_.-]+$",
    ),
]
Password = Annotated[SecretStr, Field(min_length=8, max_length=128)]


class RegistrationRequest(BaseModel):
    username: Username
    email: EmailStr = Field(max_length=254)
    password: Password

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)
    password: Password

    @field_validator("identifier", mode="before")
    @classmethod
    def trim_identifier(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    created_at: datetime


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
