from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.database import router as database_router
from app.api.routes.health import router as health_router
from app.api.routes.users import router as users_router
from app.api.routes.websockets import router as websockets_router
from app.core.config import get_allowed_origins


def create_app() -> FastAPI:
    application = FastAPI(title="Relay API", version="0.1.0")
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
