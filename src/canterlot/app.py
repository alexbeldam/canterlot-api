from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from canterlot.config import get_settings
from canterlot.config.database import DatabaseManager
from canterlot.middleware import LastSeenMiddleware
from canterlot.routers import router
from canterlot.routers.errors import register_error_handlers
from canterlot.routers.health import health_router
from canterlot.routers.webhooks import webhooks_router
from canterlot.utils import setup_logging

STATIC_DIR = Path(__file__).parent / "static"
FAVICON_URL = "/static/favicon.svg"


@asynccontextmanager
async def lifespan(_app: FastAPI):  # pragma: no cover
    setup_logging(get_settings().environment)

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

    openapi_schema["servers"] = [{"url": "/v1", "description": "v1 Base Environment"}]

    clean_paths = {}
    for path, path_item in openapi_schema.get("paths", {}).items():
        if path.startswith("/v1"):
            clean_path = path.replace("/v1", "", 1)
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
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LastSeenMiddleware)

    register_error_handlers(app)
    app.include_router(router)
    app.include_router(webhooks_router, include_in_schema=False)
    app.include_router(health_router, include_in_schema=False)
    app.openapi = lambda: custom_openapi(app)  # type: ignore[method-assign]
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/v1", include_in_schema=False)
    async def redirect_to_docs():
        return RedirectResponse(url="/docs")

    @app.get("/docs", include_in_schema=False)
    async def custom_docs():
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "",
            title=f"{app.title} - Docs",
            swagger_favicon_url=FAVICON_URL,
        )

    @app.get("/redoc", include_in_schema=False)
    async def custom_redoc():
        return get_redoc_html(
            openapi_url=app.openapi_url or "",
            title=f"{app.title} - ReDoc",
            redoc_favicon_url=FAVICON_URL,
        )

    return app
