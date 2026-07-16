from collections import Counter
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
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

        assert "/users" in schema["paths"]
        assert not any(path.startswith("/v1") for path in schema["paths"])

    def it_excludes_the_hidden_swagger_only_login_shim():
        app = create_app()

        schema = custom_openapi(app)

        assert "/auth/login" not in schema["paths"]

    def it_maps_the_bare_api_v1_root_path_to_a_slash():
        app = FastAPI()

        @app.get("/v1")
        async def _root():
            return {}

        schema = custom_openapi(app)

        assert "/" in schema["paths"]

    def it_declares_the_api_v1_server_prefix():
        app = create_app()

        schema = custom_openapi(app)

        assert schema["servers"] == [{"url": "/v1", "description": "v1 Base Environment"}]


def describe_operation_ids():
    def _schema_routes(app: FastAPI) -> list[RouteContext]:
        return [
            route
            for route in iter_route_contexts(app.routes)
            if isinstance(route.original_route, APIRoute) and route.include_in_schema
        ]

    def it_sets_an_explicit_operation_id_on_every_documented_route():
        app = create_app()

        for route in _schema_routes(app):
            assert route.operation_id, f"{route.methods} {route.path} is missing an explicit operation_id"

    def it_never_reuses_an_operation_id_across_routes():
        app = create_app()

        operation_ids = [route.operation_id for route in _schema_routes(app)]
        duplicates = [operation_id for operation_id, count in Counter(operation_ids).items() if count > 1]

        assert not duplicates, f"operation_id(s) reused across routes: {duplicates}"


def describe_custom_docs():
    def it_serves_the_swagger_ui_with_the_branded_favicon():
        with _client_without_lifespan(create_app()) as client:
            response = client.get("/docs")

        assert response.status_code == 200
        assert "/static/favicon.svg" in response.text

    def it_serves_the_redoc_ui_with_the_branded_favicon():
        with _client_without_lifespan(create_app()) as client:
            response = client.get("/redoc")

        assert response.status_code == 200
        assert "/static/favicon.svg" in response.text


def describe_root_redirects():
    def it_redirects_the_bare_root_to_the_docs():
        with _client_without_lifespan(create_app()) as client:
            response = client.get("/", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "/docs"

    def it_redirects_the_api_v1_root_to_the_docs():
        with _client_without_lifespan(create_app()) as client:
            response = client.get("/v1", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "/docs"
