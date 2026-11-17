from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.database import router as database_router
from app.api.routes.health import router as health_router
from app.api.routes.users import router as users_router
from app.api.routes.websockets import router as websockets_router

app = FastAPI(title="Relay API", version="0.1.0")
app.include_router(health_router)
app.include_router(database_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(conversations_router)
app.include_router(websockets_router)
