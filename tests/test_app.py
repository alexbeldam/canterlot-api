from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.testclient import TestClient

from canterlot.app import create_app, custom_openapi


def _client_without_lifespan(app: FastAPI) -> TestClient:
    @asynccontextmanager
    async def _noop_lifespan(_app: FastAPI):
        yield

    app.router.lifespan_context = _noop_lifespan
    return TestClient(app, raise_server_exceptions=False)


def describe_custom_openapi():
    def it_returns_the_cached_schema_when_already_computed():
        app = create_app()
        app.openapi_schema = {"cached": True}

        assert custom_openapi(app) == {"cached": True}

    def it_strips_the_api_v1_prefix_from_documented_paths():
        app = create_app()

        schema = custom_openapi(app)

        assert "/auth/register" in schema["paths"]
        assert not any(path.startswith("/api/v1") for path in schema["paths"])

    def it_maps_the_bare_api_v1_root_path_to_a_slash():
        app = FastAPI()

        @app.get("/api/v1")
        async def _root():
            return {}

        schema = custom_openapi(app)

        assert "/" in schema["paths"]

    def it_declares_the_api_v1_server_prefix():
        app = create_app()

        schema = custom_openapi(app)

        assert schema["servers"] == [{"url": "/api/v1", "description": "v1 Base Environment"}]


def describe_root_redirects():
    def it_redirects_the_bare_root_to_the_docs():
        with _client_without_lifespan(create_app()) as client:
            response = client.get("/", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "/docs"

    def it_redirects_the_api_v1_root_to_the_docs():
        with _client_without_lifespan(create_app()) as client:
            response = client.get("/api/v1", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "/docs"
