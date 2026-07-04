from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse

from canterlot.config import settings
from canterlot.config.database import DatabaseManager
from canterlot.routers import router
from canterlot.routers.errors import register_error_handlers
from canterlot.utils import setup_logging


@asynccontextmanager
async def lifespan(_app: FastAPI):  # pragma: no cover
    setup_logging(settings.environment)

    async with DatabaseManager():
        yield


def custom_openapi(app: FastAPI):
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    openapi_schema["servers"] = [{"url": "/api/v1", "description": "v1 Base Environment"}]

    clean_paths = {}
    for path, path_item in openapi_schema.get("paths", {}).items():
        if path.startswith("/api/v1"):
            clean_path = path.replace("/api/v1", "", 1)
            clean_path = clean_path if clean_path.strip() else "/"
            clean_paths[clean_path] = path_item
        else:
            clean_paths[path] = path_item

    openapi_schema["paths"] = clean_paths
    app.openapi_schema = openapi_schema
    return app.openapi_schema


def create_app() -> FastAPI:
    app = FastAPI(
        title="CanterlotAPI",
        description="API for a Book Club management system",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(router)
    app.openapi = lambda: custom_openapi(app)  # type: ignore[method-assign]

    @app.get("/", include_in_schema=False)
    @app.get("/api/v1", include_in_schema=False)
    async def redirect_to_docs():
        return RedirectResponse(url="/docs")

    return app
