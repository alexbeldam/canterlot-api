import base64
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId
from starlette.applications import Starlette
from starlette.authentication import requires
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from canterlot.middlewares import AdminAuthBackend, LastSeenMiddleware, on_auth_error
from canterlot.repositories.beanie.user import BeanieUserRepository
from canterlot.utils import create_access_token, create_jwt_token

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


async def _ping(_request):
    return PlainTextResponse("ok")


@requires("admin_authenticated")
async def _admin_ping(request):  # noqa: ARG001
    return PlainTextResponse("admin ok")


def _app() -> Starlette:
    app = Starlette(routes=[Route("/ping", _ping)])
    app.add_middleware(LastSeenMiddleware)
    return app


def _admin_app(user="admin", password="password") -> Starlette:
    app = Starlette(routes=[Route("/admin/ping", _admin_ping)])
    app.add_middleware(
        AuthenticationMiddleware,
        backend=AdminAuthBackend(admin_user=user, admin_pass=password),
        on_error=on_auth_error,
    )
    return app


def describe_last_seen_middleware():
    async def it_stamps_last_seen_at_for_an_authenticated_request(monkeypatch: pytest.MonkeyPatch):
        token = create_access_token(SOME_USER_ID)
        mock_touch = AsyncMock(return_value=True)
        monkeypatch.setattr(BeanieUserRepository, "touch_last_seen", mock_touch)

        client = TestClient(_app())
        response = client.get("/ping", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        mock_touch.assert_awaited_once()

    async def it_does_not_touch_last_seen_at_for_an_unauthenticated_request(monkeypatch: pytest.MonkeyPatch):
        mock_touch = AsyncMock()
        monkeypatch.setattr(BeanieUserRepository, "touch_last_seen", mock_touch)

        client = TestClient(_app())
        response = client.get("/ping")

        assert response.status_code == 200
        mock_touch.assert_not_called()

    async def it_ignores_a_malformed_bearer_token(monkeypatch: pytest.MonkeyPatch):
        mock_touch = AsyncMock()
        monkeypatch.setattr(BeanieUserRepository, "touch_last_seen", mock_touch)

        client = TestClient(_app())
        response = client.get("/ping", headers={"Authorization": "Bearer not-a-real-token"})

        assert response.status_code == 200
        mock_touch.assert_not_called()

    async def it_ignores_a_refresh_token_presented_as_a_bearer_token(monkeypatch: pytest.MonkeyPatch):
        refresh_token = create_jwt_token({"sub": str(SOME_USER_ID), "type": "refresh"}, timedelta(minutes=5))
        mock_touch = AsyncMock()
        monkeypatch.setattr(BeanieUserRepository, "touch_last_seen", mock_touch)

        client = TestClient(_app())
        response = client.get("/ping", headers={"Authorization": f"Bearer {refresh_token}"})

        assert response.status_code == 200
        mock_touch.assert_not_called()

    async def it_ignores_a_well_formed_token_for_a_deleted_user(monkeypatch: pytest.MonkeyPatch):
        token = create_access_token(PydanticObjectId())
        mock_touch = AsyncMock(return_value=False)
        monkeypatch.setattr(BeanieUserRepository, "touch_last_seen", mock_touch)

        client = TestClient(_app())
        response = client.get("/ping", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        mock_touch.assert_awaited_once()

    async def it_does_not_fail_the_request_when_the_repository_write_fails(monkeypatch: pytest.MonkeyPatch):
        token = create_access_token(SOME_USER_ID)
        mock_touch = AsyncMock(side_effect=RuntimeError("mongo is down"))
        monkeypatch.setattr(BeanieUserRepository, "touch_last_seen", mock_touch)

        client = TestClient(_app())
        response = client.get("/ping", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        mock_touch.assert_awaited_once()


def describe_admin_auth_backend():
    def it_authenticates_valid_basic_credentials():
        client = TestClient(_admin_app("admin", "secret"))
        creds = base64.b64encode(b"admin:secret").decode("utf-8")

        response = client.get("/admin/ping", headers={"Authorization": f"Basic {creds}"})

        assert response.status_code == 200
        assert response.text == "admin ok"

    def it_rejects_missing_authorization_header():
        client = TestClient(_admin_app())

        response = client.get("/admin/ping")

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == 'Basic realm="Admin Dashboard Access Control"'
        assert response.text == "Unauthorized Access"

    def it_rejects_non_basic_auth_scheme():
        client = TestClient(_admin_app())

        response = client.get("/admin/ping", headers={"Authorization": "Bearer not-basic"})

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == 'Basic realm="Admin Dashboard Access Control"'

    def it_rejects_invalid_username_or_password():
        client = TestClient(_admin_app("admin", "secret"))
        creds = base64.b64encode(b"admin:wrongpassword").decode("utf-8")

        response = client.get("/admin/ping", headers={"Authorization": f"Basic {creds}"})

        assert response.status_code == 401

    def it_rejects_malformed_base64_payloads():
        client = TestClient(_admin_app())

        response = client.get("/admin/ping", headers={"Authorization": "Basic !!!not-valid-base64!!!"})

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == 'Basic realm="Admin Dashboard Access Control"'
