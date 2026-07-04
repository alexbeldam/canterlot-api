from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.exceptions import (
    ClubNotFoundError,
    DirectInviteIdentityMismatchError,
    InvalidInviteTokenError,
    InviteLinkDeactivatedError,
)
from canterlot.models.club import ClubOnboarding
from canterlot.models.enums import ClubOnboardingStatus
from canterlot.services.invite import InviteValidationResult

SOME_INVITE_ID = "some-invite-id"
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def describe_accept_invitation():
    def it_returns_the_onboarding_result_on_success(
        client: TestClient, invite_service: AsyncMock, club_service: AsyncMock
    ):
        invite_service.validate_incoming_invite.return_value = InviteValidationResult(
            club_id=SOME_CLUB_ID, club_name="Book Club", invited_by=None, is_direct=False
        )
        club_service.admit_user.return_value = ClubOnboarding(club_name="Book Club", status=ClubOnboardingStatus.JOINED)

        response = client.post(f"/api/v1/invites/{SOME_INVITE_ID}/accept")

        assert response.status_code == 200
        assert response.json()["status"] == "JOINED"
        invite_service.register_invite_usage.assert_awaited_once_with(SOME_INVITE_ID)

    def it_does_not_register_usage_when_the_user_was_already_a_member(
        client: TestClient, invite_service: AsyncMock, club_service: AsyncMock
    ):
        invite_service.validate_incoming_invite.return_value = InviteValidationResult(
            club_id=SOME_CLUB_ID, club_name="Book Club", invited_by=None, is_direct=False
        )
        club_service.admit_user.return_value = ClubOnboarding(
            club_name="Book Club", status=ClubOnboardingStatus.ALREADY_MEMBER
        )

        response = client.post(f"/api/v1/invites/{SOME_INVITE_ID}/accept")

        assert response.status_code == 200
        invite_service.register_invite_usage.assert_not_called()

    def it_returns_400_for_an_invalid_invite_token(client: TestClient, invite_service: AsyncMock):
        invite_service.validate_incoming_invite.side_effect = InvalidInviteTokenError("bad token")

        response = client.post(f"/api/v1/invites/{SOME_INVITE_ID}/accept")

        assert response.status_code == 400
        assert response.json()["error"]["error_code"] == "INVALID_INVITE_TOKEN"

    def it_returns_410_for_a_deactivated_invite(client: TestClient, invite_service: AsyncMock):
        invite_service.validate_incoming_invite.side_effect = InviteLinkDeactivatedError("deactivated")

        response = client.post(f"/api/v1/invites/{SOME_INVITE_ID}/accept")

        assert response.status_code == 410

    def it_returns_403_for_a_direct_invite_identity_mismatch(client: TestClient, invite_service: AsyncMock):
        invite_service.validate_incoming_invite.side_effect = DirectInviteIdentityMismatchError("mismatch")

        response = client.post(f"/api/v1/invites/{SOME_INVITE_ID}/accept")

        assert response.status_code == 403

    def it_returns_404_when_the_club_no_longer_exists(
        client: TestClient, invite_service: AsyncMock, club_service: AsyncMock
    ):
        invite_service.validate_incoming_invite.return_value = InviteValidationResult(
            club_id=SOME_CLUB_ID, club_name="Book Club", invited_by=None, is_direct=False
        )
        club_service.admit_user.side_effect = ClubNotFoundError("gone")

        response = client.post(f"/api/v1/invites/{SOME_INVITE_ID}/accept")

        assert response.status_code == 404
