from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import get_access_token_expire_minutes
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    RegistrationRequest,
    UserPublic,
    WebSocketTicketResponse,
)
from app.security.tokens import (
    InvalidAccessToken,
    create_access_token,
    get_access_token_expiration,
)
from app.security.websocket_tickets import websocket_ticket_store
from app.services.auth import (
    DuplicateUserError,
    InvalidCredentialsError,
    authenticate_user,
    register_user,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_bearer_scheme = HTTPBearer(auto_error=False)


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegistrationRequest,
    session: Session = Depends(get_db),
) -> User:
    try:
        return register_user(
            session,
            username=payload.username,
            email=str(payload.email),
            password=payload.password.get_secret_value(),
        )
    except DuplicateUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email is already registered.",
        ) from exc


@router.post("/login", response_model=AccessTokenResponse)
def login(
    payload: LoginRequest,
    session: Session = Depends(get_db),
) -> AccessTokenResponse:
    try:
        user = authenticate_user(
            session,
            identifier=payload.identifier,
            password=payload.password.get_secret_value(),
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return AccessTokenResponse(
        access_token=create_access_token(user.id),
        expires_in=get_access_token_expire_minutes() * 60,
    )


@router.get("/me", response_model=UserPublic)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/websocket-ticket", response_model=WebSocketTicketResponse)
def issue_websocket_ticket(
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> WebSocketTicketResponse:
    """Issue a one-use WebSocket ticket bounded by the current JWT expiry."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        ticket, expires_in = websocket_ticket_store.issue(
            current_user.id,
            get_access_token_expiration(credentials.credentials),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="WebSocket ticket service unavailable.") from exc
    except (ValueError, InvalidAccessToken, jwt.InvalidTokenError) as exc:
        raise HTTPException(status_code=401, detail="Not authenticated") from exc
    return WebSocketTicketResponse(ticket=ticket, expires_in=expires_in)
