from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.dto.club import ClubOnboarding
from canterlot.dto.invite import InvitePreviewResponse
from canterlot.exceptions import (
    ClubNotFoundError,
    DirectInviteIdentityMismatchError,
    InvalidInviteTokenError,
    InviteLinkDeactivatedError,
)
from canterlot.services.invite import InviteValidationResult
from canterlot.types import ClubOnboardingStatus, InviteType, JoinPolicy

SOME_INVITE_ID = "some-invite-id"
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def describe_preview_invitation():
    def it_returns_preview_metadata_on_success(client: TestClient, invite_service: AsyncMock):
        invite_service.get_preview_metadata.return_value = InvitePreviewResponse(
            club_slug="book-club",
            club_name="Book Club",
            join_policy=JoinPolicy.PUBLIC,
            invite_type=InviteType.PUBLIC,
            invited_by_username="rarity",
        )

        response = client.get(f"/v1/invites/{SOME_INVITE_ID}/preview")

        assert response.status_code == 200
        assert response.json() == {
            "club_slug": "book-club",
            "club_name": "Book Club",
            "join_policy": "PUBLIC",
            "invite_type": "PUBLIC",
            "invited_by_username": "rarity",
        }
        invite_service.get_preview_metadata.assert_awaited_once_with(SOME_INVITE_ID, invited_by=None)

    def it_forwards_the_invited_by_query_param(client: TestClient, invite_service: AsyncMock):
        invite_service.get_preview_metadata.return_value = InvitePreviewResponse(
            club_slug="book-club",
            club_name="Book Club",
            join_policy=JoinPolicy.PUBLIC,
            invite_type=InviteType.PUBLIC,
            invited_by_username="rarity",
        )

        response = client.get(f"/v1/invites/{SOME_INVITE_ID}/preview", params={"invited_by": "rarity"})

        assert response.status_code == 200
        invite_service.get_preview_metadata.assert_awaited_once_with(SOME_INVITE_ID, invited_by="rarity")

    def it_returns_400_for_an_invalid_invite_token(client: TestClient, invite_service: AsyncMock):
        invite_service.get_preview_metadata.side_effect = InvalidInviteTokenError("bad token")

        response = client.get(f"/v1/invites/{SOME_INVITE_ID}/preview")

        assert response.status_code == 400
        assert response.json()["error"]["error_code"] == "INVALID_INVITE_TOKEN"

    def it_returns_410_for_a_deactivated_invite(client: TestClient, invite_service: AsyncMock):
        invite_service.get_preview_metadata.side_effect = InviteLinkDeactivatedError("deactivated")

        response = client.get(f"/v1/invites/{SOME_INVITE_ID}/preview")

        assert response.status_code == 410

    def it_returns_404_when_the_club_no_longer_exists(client: TestClient, invite_service: AsyncMock):
        invite_service.get_preview_metadata.side_effect = ClubNotFoundError("gone")

        response = client.get(f"/v1/invites/{SOME_INVITE_ID}/preview")

        assert response.status_code == 404


def describe_accept_invitation():
    def it_returns_200_when_joined_outright(client: TestClient, invite_service: AsyncMock, club_service: AsyncMock):
        invite_service.validate_incoming_invite.return_value = InviteValidationResult(
            club_id=SOME_CLUB_ID, club_name="Book Club", invited_by=None, is_direct=False
        )
        club_service.admit_user.return_value = ClubOnboarding(club_name="Book Club", status=ClubOnboardingStatus.JOINED)

        response = client.patch(f"/v1/invites/{SOME_INVITE_ID}")

        assert response.status_code == 200
        assert response.json()["status"] == "JOINED"
        invite_service.register_invite_usage.assert_awaited_once_with(SOME_INVITE_ID)

    def it_returns_202_when_queued_for_approval(client: TestClient, invite_service: AsyncMock, club_service: AsyncMock):
        invite_service.validate_incoming_invite.return_value = InviteValidationResult(
            club_id=SOME_CLUB_ID, club_name="Book Club", invited_by=None, is_direct=False
        )
        club_service.admit_user.return_value = ClubOnboarding(
            club_name="Book Club", status=ClubOnboardingStatus.PENDING_APPROVAL
        )

        response = client.patch(f"/v1/invites/{SOME_INVITE_ID}")

        assert response.status_code == 202
        assert response.json()["status"] == "PENDING_APPROVAL"
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

        response = client.patch(f"/v1/invites/{SOME_INVITE_ID}")

        assert response.status_code == 200
        invite_service.register_invite_usage.assert_not_called()

    def it_returns_403_and_does_not_register_usage_when_the_user_is_banned(
        client: TestClient, invite_service: AsyncMock, club_service: AsyncMock
    ):
        invite_service.validate_incoming_invite.return_value = InviteValidationResult(
            club_id=SOME_CLUB_ID, club_name="Book Club", invited_by=None, is_direct=False
        )
        club_service.admit_user.return_value = ClubOnboarding(club_name="Book Club", status=ClubOnboardingStatus.BANNED)

        response = client.patch(f"/v1/invites/{SOME_INVITE_ID}")

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "MEMBER_BANNED"
        invite_service.register_invite_usage.assert_not_called()

    def it_returns_400_for_an_invalid_invite_token(client: TestClient, invite_service: AsyncMock):
        invite_service.validate_incoming_invite.side_effect = InvalidInviteTokenError("bad token")

        response = client.patch(f"/v1/invites/{SOME_INVITE_ID}")

        assert response.status_code == 400
        assert response.json()["error"]["error_code"] == "INVALID_INVITE_TOKEN"

    def it_returns_410_for_a_deactivated_invite(client: TestClient, invite_service: AsyncMock):
        invite_service.validate_incoming_invite.side_effect = InviteLinkDeactivatedError("deactivated")

        response = client.patch(f"/v1/invites/{SOME_INVITE_ID}")

        assert response.status_code == 410

    def it_returns_403_for_a_direct_invite_identity_mismatch(client: TestClient, invite_service: AsyncMock):
        invite_service.validate_incoming_invite.side_effect = DirectInviteIdentityMismatchError("mismatch")

        response = client.patch(f"/v1/invites/{SOME_INVITE_ID}")

        assert response.status_code == 403

    def it_returns_404_when_the_club_no_longer_exists(
        client: TestClient, invite_service: AsyncMock, club_service: AsyncMock
    ):
        invite_service.validate_incoming_invite.return_value = InviteValidationResult(
            club_id=SOME_CLUB_ID, club_name="Book Club", invited_by=None, is_direct=False
        )
        club_service.admit_user.side_effect = ClubNotFoundError("gone")

        response = client.patch(f"/v1/invites/{SOME_INVITE_ID}")

        assert response.status_code == 404
