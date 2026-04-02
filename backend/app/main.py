from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.routes.media import router as media_router
from app.routes.search import router as search_router
from app.services.persistence_service import PersistenceService

def _resolve_frontend_dist(settings: Settings) -> Path:
    configured_path = Path(settings.frontend_dist_dir)
    if configured_path.is_absolute():
        return configured_path
    return Path.cwd() / configured_path


def _configure_frontend_routes(app: FastAPI, settings: Settings) -> None:
    frontend_dist_dir = _resolve_frontend_dist(settings)
    frontend_index = frontend_dist_dir / "index.html"
    assets_dir = frontend_dist_dir / "assets"

    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    async def serve_frontend_file(path: str = "") -> FileResponse:
        if not frontend_index.is_file():
            raise HTTPException(status_code=404, detail="Frontend build not found")

        requested_path = path.strip("/")
        if requested_path:
            candidate = (frontend_dist_dir / requested_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(frontend_dist_dir.resolve()):
                return FileResponse(candidate)

        return FileResponse(frontend_index)

    @app.get("/", include_in_schema=False)
    async def frontend_index_route() -> FileResponse:
        return await serve_frontend_file()

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend_spa_route(path: str) -> FileResponse:
        return await serve_frontend_file(path)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    PersistenceService(resolved_settings).initialize()
    allow_all_origins = resolved_settings.cors_allow_origins.strip() == "*"
    allow_origins = (
        ["*"]
        if allow_all_origins
        else [item.strip() for item in resolved_settings.cors_allow_origins.split(",") if item.strip()]
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield

    app = FastAPI(title=resolved_settings.app_name, lifespan=lifespan)
    app.state.settings = resolved_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=not allow_all_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(search_router)
    app.include_router(media_router)
    _configure_frontend_routes(app, resolved_settings)
    return app


app = create_app()
