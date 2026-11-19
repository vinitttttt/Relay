from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
import logging
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import (
    get_access_token_expire_minutes,
    get_rate_limit,
    get_rate_limit_window_seconds,
)
from app.core.rate_limit import check_rate_limit
from app.core.logging import log_exception
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
logger = logging.getLogger("relay.auth")
_bearer_scheme = HTTPBearer(auto_error=False)


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegistrationRequest,
    request: Request,
    session: Session = Depends(get_db),
) -> User:
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(
        "register", client_ip,
        get_rate_limit("REGISTER", 5),
        get_rate_limit_window_seconds("REGISTER", 3600),
    )
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
    except Exception as exc:
        log_exception(
            logger, "authentication.registration_error", exc,
            method=request.method, path=request.url.path,
        )
        raise HTTPException(status_code=500, detail="Registration could not be completed.") from None


@router.post("/login", response_model=AccessTokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    session: Session = Depends(get_db),
) -> AccessTokenResponse:
    client_ip = request.client.host if request.client else "unknown"
    login_limit = get_rate_limit("LOGIN", 10)
    login_window = get_rate_limit_window_seconds("LOGIN", 60)
    check_rate_limit("login_ip", client_ip, login_limit, login_window)
    check_rate_limit(
        "login_identifier", payload.identifier.strip().casefold(),
        login_limit, login_window,
    )
    try:
        user = authenticate_user(
            session,
            identifier=payload.identifier,
            password=payload.password.get_secret_value(),
        )
    except InvalidCredentialsError as exc:
        logger.warning(
            "Authentication failed",
            extra={
                "event": "authentication.failed",
                "method": request.method,
                "path": request.url.path,
                "status_code": status.HTTP_401_UNAUTHORIZED,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except Exception as exc:
        log_exception(
            logger, "authentication.login_error", exc,
            method=request.method, path=request.url.path,
        )
        raise HTTPException(status_code=500, detail="Authentication could not be completed.") from None

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
        logger.warning(
            "WebSocket ticket service unavailable",
            extra={
                "event": "authentication.websocket_ticket_unavailable",
                "user_id": current_user.id,
                "status_code": 503,
            },
        )
        raise HTTPException(status_code=503, detail="WebSocket ticket service unavailable.") from exc
    except (ValueError, InvalidAccessToken, jwt.InvalidTokenError) as exc:
        raise HTTPException(status_code=401, detail="Not authenticated") from exc
    return WebSocketTicketResponse(ticket=ticket, expires_in=expires_in)
