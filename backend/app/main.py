from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes.search import router as search_router
from app.services.persistence_service import PersistenceService

settings = get_settings()
allow_all_origins = settings.cors_allow_origins.strip() == "*"
allow_origins = (
    ["*"]
    if allow_all_origins
    else [item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()]
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    PersistenceService(settings).initialize()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(search_router)
