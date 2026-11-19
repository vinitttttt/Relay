from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.auth import router as auth_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.database import router as database_router
from app.api.routes.health import router as health_router
from app.api.routes.users import router as users_router
from app.api.routes.websockets import router as websockets_router
from app.core.config import get_allowed_origins
from app.core.logging import configure_logging, log_exception

logger = logging.getLogger("relay.api")


def create_app() -> FastAPI:
    configure_logging()

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        logger.info("Application started", extra={"event": "application.started"})
        try:
            yield
        finally:
            logger.info("Application stopped", extra={"event": "application.stopped"})

    application = FastAPI(title="Relay API", version="0.1.0", lifespan=lifespan)

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code not in (401, 429):
            logger.log(
                logging.ERROR if exc.status_code >= 500 else logging.WARNING,
                "HTTP request failed",
                extra={
                    "event": "http.request_failed",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": exc.status_code,
                },
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder({"detail": exc.detail}),
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        errors = [
            {key: error[key] for key in ("type", "loc", "msg") if key in error}
            for error in exc.errors()
        ]
        logger.warning(
            "Request validation failed",
            extra={
                "event": "http.validation_failed",
                "method": request.method,
                "path": request.url.path,
                "status_code": 422,
            },
        )
        return JSONResponse(status_code=422, content={"detail": errors})

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        log_exception(
            logger,
            "http.unexpected_error",
            exc,
            method=request.method,
            path=request.url.path,
            status_code=500,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."},
        )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    application.include_router(health_router)
    application.include_router(database_router)
    application.include_router(auth_router)
    application.include_router(users_router)
    application.include_router(conversations_router)
    application.include_router(websockets_router)
    return application


app = create_app()
