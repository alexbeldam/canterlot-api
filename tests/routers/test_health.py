from unittest.mock import AsyncMock

from starlette.testclient import TestClient


def describe_check_health():
    def it_returns_200_when_every_dependency_is_reachable(client: TestClient, health_service: AsyncMock):
        health_service.check.return_value = True

        response = client.get("/health")

        assert response.status_code == 200

    def it_returns_503_when_a_dependency_is_unreachable(client: TestClient, health_service: AsyncMock):
        health_service.check.return_value = False

        response = client.get("/health")

        assert response.status_code == 503

    def it_is_excluded_from_the_openapi_schema(client: TestClient):
        schema = client.get("/openapi.json").json()

        assert "/health" not in schema["paths"]
