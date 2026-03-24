from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes.search import router as search_router

settings = get_settings()
allow_all_origins = settings.cors_allow_origins.strip() == "*"
allow_origins = (
    ["*"]
    if allow_all_origins
    else [item.strip() for item in settings.cors_allow_origins.split(",") if item.strip()]
)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=not allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(search_router)
