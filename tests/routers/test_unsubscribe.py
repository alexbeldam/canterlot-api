from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from canterlot.config import get_settings
from canterlot.utils.security import UnsubscribeScope


def describe_one_click_unsubscribe():
    def it_processes_a_valid_rfc_8058_request(client: TestClient, process_unsubscribe_use_case: AsyncMock):
        process_unsubscribe_use_case.execute.return_value = UnsubscribeScope.CLUB

        response = client.post(
            "/v1/unsubscribe",
            params={"token": "some-unsubscribe-token"},
            data={"List-Unsubscribe": "One-Click"},
        )

        assert response.status_code == 204
        process_unsubscribe_use_case.execute.assert_awaited_once_with("some-unsubscribe-token")

    def it_rejects_a_request_missing_the_one_click_form_field(
        client: TestClient, process_unsubscribe_use_case: AsyncMock
    ):
        response = client.post("/v1/unsubscribe", params={"token": "some-unsubscribe-token"})

        assert response.status_code == 400
        assert response.json()["error"]["error_code"] == "INVALID_UNSUBSCRIBE_PAYLOAD"
        process_unsubscribe_use_case.execute.assert_not_called()

    def it_rejects_a_request_with_the_wrong_form_value(client: TestClient, process_unsubscribe_use_case: AsyncMock):
        response = client.post(
            "/v1/unsubscribe",
            params={"token": "some-unsubscribe-token"},
            data={"List-Unsubscribe": "Unsubscribe"},
        )

        assert response.status_code == 400
        process_unsubscribe_use_case.execute.assert_not_called()


def describe_browser_unsubscribe():
    def it_redirects_to_the_frontend_with_the_resolved_scope(
        client: TestClient, process_unsubscribe_use_case: AsyncMock
    ):
        process_unsubscribe_use_case.execute.return_value = UnsubscribeScope.CATEGORY

        response = client.get(
            "/v1/unsubscribe",
            params={"token": "some-unsubscribe-token"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        frontend_url = get_settings().frontend_url
        assert response.headers["location"] == f"{frontend_url}/unsubscribed?scope=category&status=success"
        process_unsubscribe_use_case.execute.assert_awaited_once_with("some-unsubscribe-token")
