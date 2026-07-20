from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from canterlot.middlewares import LastSeenMiddleware
from canterlot.models.user import UserModel
from canterlot.repositories.beanie.user import BeanieUserRepository
from canterlot.utils import create_access_token, create_jwt_token

pytestmark = pytest.mark.asyncio(loop_scope="session")

_counter = 0


async def _ping(_request):
    return PlainTextResponse("ok")


def _app() -> Starlette:
    app = Starlette(routes=[Route("/ping", _ping)])
    app.add_middleware(LastSeenMiddleware)
    return app


async def _user(**overrides: object) -> UserModel:
    global _counter
    _counter += 1
    defaults = {
        "name": "Twilight Sparkle",
        "username": f"user{_counter}",
        "email": f"user{_counter}@example.com",
    }
    return await UserModel(**{**defaults, **overrides}).insert()


def describe_last_seen_middleware():
    async def it_stamps_last_seen_at_for_an_authenticated_request():
        user = await _user()
        token = create_access_token(PydanticObjectId(user.id))
        client = TestClient(_app())

        response = client.get("/ping", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        found = await UserModel.get(user.id)
        assert found is not None
        assert found.last_seen_at is not None

    async def it_does_not_touch_last_seen_at_for_an_unauthenticated_request():
        client = TestClient(_app())

        response = client.get("/ping")

        assert response.status_code == 200

    async def it_ignores_a_malformed_bearer_token():
        client = TestClient(_app())

        response = client.get("/ping", headers={"Authorization": "Bearer not-a-real-token"})

        assert response.status_code == 200

    async def it_ignores_a_refresh_token_presented_as_a_bearer_token():
        user = await _user()
        refresh_token = create_jwt_token({"sub": str(user.id), "type": "refresh"}, timedelta(minutes=5))
        client = TestClient(_app())

        response = client.get("/ping", headers={"Authorization": f"Bearer {refresh_token}"})

        assert response.status_code == 200
        found = await UserModel.get(user.id)
        assert found is not None
        assert found.last_seen_at is None

    async def it_ignores_a_well_formed_token_for_a_deleted_user():
        token = create_access_token(PydanticObjectId())
        client = TestClient(_app())

        response = client.get("/ping", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200

    async def it_does_not_fail_the_request_when_the_repository_write_fails(monkeypatch: pytest.MonkeyPatch):
        async def _boom(_self, _user_id, _now):
            raise RuntimeError("mongo is down")

        monkeypatch.setattr(BeanieUserRepository, "touch_last_seen", _boom)
        user = await _user()
        token = create_access_token(PydanticObjectId(user.id))
        client = TestClient(_app())

        response = client.get("/ping", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200

    async def it_does_not_rewrite_a_stamp_from_earlier_today():
        recent = datetime.now(UTC) - timedelta(hours=1)
        user = await _user(last_seen_at=recent)
        before = await UserModel.get(user.id)
        assert before is not None
        token = create_access_token(PydanticObjectId(user.id))
        client = TestClient(_app())

        response = client.get("/ping", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        found = await UserModel.get(user.id)
        assert found is not None
        assert found.last_seen_at == before.last_seen_at
