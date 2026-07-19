from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from pydantic import HttpUrl
from starlette.testclient import TestClient

from canterlot.exceptions import (
    CannotChangeOwnerRoleError,
    CannotTransferOwnershipToSelfError,
    ClubMemberNotFoundError,
    ClubNotFoundError,
    ClubOwnerCannotLeaveError,
    FormerOwnerProtectedError,
    InviteLinkDeactivatedError,
    MemberRoleChangeConflictError,
    OwnershipReclaimWindowExpiredError,
    OwnershipTransferConflictError,
    OwnershipTransferCooldownError,
    PendingRequestNotFoundError,
    UnauthorizedClubMemberError,
    UserNotFoundError,
)
from canterlot.models.club import ClubModel, MemberSchema, PendingApprovalSchema
from canterlot.models.user import AvatarSchema, UserModel
from canterlot.services.club import ClubView
from canterlot.types import AuthProviderName, MemberRole

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_SLUG = "book-club"
SOME_OWNER_ID = PydanticObjectId("507f1f77bcf86cd799439011")  # matches conftest's `current_user` fixture
SOME_PENDING_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_PENDING_USERNAME = "bob_2"
SOME_TARGET_ID = PydanticObjectId("507f1f77bcf86cd799439013")
SOME_TARGET_USERNAME = "carol_3"


def _created_club() -> ClubModel:
    return ClubModel(
        name="Book Club",
        slug="book-club",
        members=[MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER)],
    )


def _club_view(
    role: MemberRole,
    pending_usernames: dict[PydanticObjectId, str] | None = None,
    club: ClubModel | None = None,
) -> ClubView:
    return ClubView(
        club=club or _created_club(),
        member_usernames={SOME_OWNER_ID: "alice_1"},
        viewer_role=role,
        pending_usernames=pending_usernames,
    )


def describe_create_club():
    def it_creates_a_club_and_returns_it(client: TestClient, club_service: AsyncMock, invite_service: AsyncMock):
        club_service.create_new_club.return_value = _created_club()
        club_service.resolve_member_usernames.return_value = {SOME_OWNER_ID: "alice_1"}

        response = client.post("/v1/clubs", json={"name": "Book Club"})

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Book Club"
        assert body["slug"] == "book-club"
        assert body["members"][0]["username"] == "alice_1"
        assert body["members"][0]["role"] == "OWNER"
        assert "id" not in body
        assert response.headers["Location"] == "/v1/clubs/book-club"
        invite_service.rotate_public_link.assert_awaited_once()

    def it_does_not_leak_the_internal_object_id(client: TestClient, club_service: AsyncMock):
        club_service.create_new_club.return_value = _created_club()
        club_service.resolve_member_usernames.return_value = {SOME_OWNER_ID: "alice_1"}

        response = client.post("/v1/clubs", json={"name": "Book Club"})

        body = response.json()
        assert "id" not in body
        assert "_id" not in body

    def it_returns_422_for_a_name_that_is_too_short(client: TestClient, club_service: AsyncMock):
        response = client.post("/v1/clubs", json={"name": "ab"})

        assert response.status_code == 422
        club_service.create_new_club.assert_not_called()

    def it_returns_403_when_the_initial_invite_link_cannot_be_rotated(
        client: TestClient, club_service: AsyncMock, invite_service: AsyncMock
    ):
        club_service.create_new_club.return_value = _created_club()
        invite_service.rotate_public_link.side_effect = UnauthorizedClubMemberError("cannot rotate")

        response = client.post("/v1/clubs", json={"name": "Book Club"})

        assert response.status_code == 403


def describe_get_club():
    def it_returns_the_public_shape_for_a_plain_member(client: TestClient, club_service: AsyncMock):
        club_service.get_club_view.return_value = _club_view(role=MemberRole.MEMBER)

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}")

        assert response.status_code == 200
        body = response.json()
        assert body["members"][0]["username"] == "alice_1"
        assert "pending_approvals" not in body
        assert "banned_users" not in body
        assert "id" not in body

    def it_returns_403_when_the_caller_is_not_a_member(client: TestClient, club_service: AsyncMock):
        club_service.get_club_view.side_effect = UnauthorizedClubMemberError("not a member")

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}")

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_includes_pending_approvals_for_an_owner(client: TestClient, club_service: AsyncMock):
        club = _created_club()
        club.pending_approvals = [PendingApprovalSchema(user_id=SOME_PENDING_ID)]
        club_service.get_club_view.return_value = _club_view(
            role=MemberRole.OWNER,
            pending_usernames={SOME_PENDING_ID: "bob_2"},
            club=club,
        )

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}")

        assert response.status_code == 200
        body = response.json()
        assert body["pending_approvals"][0]["username"] == "bob_2"
        assert "banned_users" not in body

    def it_includes_pending_approvals_for_an_admin(client: TestClient, club_service: AsyncMock):
        club_service.get_club_view.return_value = _club_view(role=MemberRole.ADMIN, pending_usernames={})

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}")

        assert response.status_code == 200
        assert response.json()["pending_approvals"] == []

    def it_returns_404_when_the_slug_does_not_exist(client: TestClient, club_service: AsyncMock):
        club_service.get_club_view.side_effect = ClubNotFoundError("not found")

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "CLUB_NOT_FOUND"

    def it_exposes_ownership_transfer_protection_state_to_the_protected_former_owner(
        client: TestClient, club_service: AsyncMock
    ):
        club = _created_club()
        club.ownership_transferred_at = datetime.now(UTC) - timedelta(hours=1)
        club.protected_former_owner_id = SOME_OWNER_ID
        club_service.get_club_view.return_value = _club_view(role=MemberRole.OWNER, pending_usernames={}, club=club)

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}")

        assert response.status_code == 200
        body = response.json()
        assert body["protected_former_owner"] == "alice_1"
        assert body["active_reclaim_deadline"] is not None


def describe_update_club_settings():
    def it_returns_200_with_the_updated_club(client: TestClient, club_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        updated = _created_club()
        updated.allow_suggestions = False
        club_service.update_settings.return_value = updated
        club_service.resolve_member_usernames.return_value = {SOME_OWNER_ID: "alice_1"}

        response = client.patch(f"/v1/clubs/{SOME_CLUB_SLUG}/settings", json={"allow_suggestions": False})

        assert response.status_code == 200
        body = response.json()
        assert body["allow_suggestions"] is False
        club_service.update_settings.assert_awaited_once()

    def it_returns_403_when_the_caller_lacks_privileges(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.update_settings.side_effect = UnauthorizedClubMemberError("nope")

        response = client.patch(f"/v1/clubs/{SOME_CLUB_SLUG}/settings", json={"allow_suggestions": False})

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_404_when_the_club_slug_does_not_exist(client: TestClient, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = None

        response = client.patch(f"/v1/clubs/{SOME_CLUB_SLUG}/settings", json={"allow_suggestions": False})

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "CLUB_NOT_FOUND"

    def it_returns_422_when_no_fields_are_provided(client: TestClient, club_repo: AsyncMock, club_service: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID

        response = client.patch(f"/v1/clubs/{SOME_CLUB_SLUG}/settings", json={})

        assert response.status_code == 422
        club_service.update_settings.assert_not_called()

    def it_returns_422_for_a_name_that_is_too_short(client: TestClient, club_repo: AsyncMock, club_service: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID

        response = client.patch(f"/v1/clubs/{SOME_CLUB_SLUG}/settings", json={"name": "ab"})

        assert response.status_code == 422
        club_service.update_settings.assert_not_called()


def describe_approve_pending_request():
    def it_returns_204_when_approved(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_PENDING_ID
        club_service.review_pending_request.return_value = None

        response = client.patch(f"/v1/clubs/{SOME_CLUB_SLUG}/pending-approvals/{SOME_PENDING_USERNAME}")

        assert response.status_code == 204
        club_service.review_pending_request.assert_awaited_once_with(
            SOME_CLUB_ID, SOME_OWNER_ID, SOME_PENDING_ID, approve=True
        )

    def it_returns_403_when_the_caller_is_not_owner_or_admin(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_PENDING_ID
        club_service.review_pending_request.side_effect = UnauthorizedClubMemberError("nope")

        response = client.patch(f"/v1/clubs/{SOME_CLUB_SLUG}/pending-approvals/{SOME_PENDING_USERNAME}")

        assert response.status_code == 403

    def it_returns_404_when_there_is_no_such_pending_request(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_PENDING_ID
        club_service.review_pending_request.side_effect = PendingRequestNotFoundError("not queued")

        response = client.patch(f"/v1/clubs/{SOME_CLUB_SLUG}/pending-approvals/{SOME_PENDING_USERNAME}")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "PENDING_REQUEST_NOT_FOUND"

    def it_returns_404_when_the_club_slug_does_not_exist(client: TestClient, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = None

        response = client.patch(f"/v1/clubs/{SOME_CLUB_SLUG}/pending-approvals/{SOME_PENDING_USERNAME}")

        assert response.status_code == 404

    def it_returns_404_when_the_username_does_not_exist(client: TestClient, club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = None

        response = client.patch(f"/v1/clubs/{SOME_CLUB_SLUG}/pending-approvals/{SOME_PENDING_USERNAME}")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "USER_NOT_FOUND"


def describe_reject_pending_request():
    def it_returns_204_when_rejected(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_PENDING_ID
        club_service.review_pending_request.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/pending-approvals/{SOME_PENDING_USERNAME}")

        assert response.status_code == 204
        club_service.review_pending_request.assert_awaited_once_with(
            SOME_CLUB_ID, SOME_OWNER_ID, SOME_PENDING_ID, approve=False
        )

    def it_returns_403_when_the_caller_is_not_owner_or_admin(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_PENDING_ID
        club_service.review_pending_request.side_effect = UnauthorizedClubMemberError("nope")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/pending-approvals/{SOME_PENDING_USERNAME}")

        assert response.status_code == 403

    def it_returns_404_when_there_is_no_such_pending_request(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_PENDING_ID
        club_service.review_pending_request.side_effect = PendingRequestNotFoundError("not queued")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/pending-approvals/{SOME_PENDING_USERNAME}")

        assert response.status_code == 404

    def it_returns_404_when_the_username_does_not_exist(client: TestClient, club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/pending-approvals/{SOME_PENDING_USERNAME}")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "USER_NOT_FOUND"


def describe_leave_club():
    def it_returns_204_when_left(client: TestClient, club_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.leave_club.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/members/me")

        assert response.status_code == 204
        club_service.leave_club.assert_awaited_once_with(SOME_CLUB_ID, SOME_OWNER_ID)

    def it_returns_403_when_the_caller_is_not_a_member(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.leave_club.side_effect = UnauthorizedClubMemberError("nope")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/members/me")

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_404_when_the_club_does_not_exist(client: TestClient, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/members/me")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "CLUB_NOT_FOUND"

    def it_returns_409_when_the_caller_is_the_owner(client: TestClient, club_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.leave_club.side_effect = ClubOwnerCannotLeaveError("nope")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/members/me")

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "CLUB_OWNER_CANNOT_LEAVE"

    def it_returns_409_when_the_caller_is_a_protected_former_owner(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.leave_club.side_effect = FormerOwnerProtectedError("protected")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/members/me")

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "FORMER_OWNER_PROTECTED"


def describe_get_club_member():
    def it_returns_the_target_members_profile(
        client: TestClient,
        club_service: AsyncMock,
        club_repo: AsyncMock,
        user_repo: AsyncMock,
        user_service: AsyncMock,
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.get_member_profile.return_value = MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.ADMIN)
        user_service.find_profile_by_id.return_value = UserModel(
            name="Carol Jones",
            username=SOME_TARGET_USERNAME,
            email="carol@example.com",
            avatar=AvatarSchema(
                source=AuthProviderName.GRAVATAR, value=HttpUrl("https://gravatar.com/avatar/somehash")
            ),
        )

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}")

        assert response.status_code == 200
        body = response.json()
        assert body["username"] == SOME_TARGET_USERNAME
        assert body["name"] == "Carol Jones"
        assert body["role"] == "ADMIN"
        assert body["avatar"] == {"source": "GRAVATAR", "value": "https://gravatar.com/avatar/somehash"}
        assert "email" not in body
        club_service.get_member_profile.assert_awaited_once_with(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID)

    def it_returns_403_when_the_caller_is_not_a_member(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.get_member_profile.side_effect = UnauthorizedClubMemberError("not a member")

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}")

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_404_when_the_target_is_not_a_member(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.get_member_profile.side_effect = ClubMemberNotFoundError("not a member")

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "CLUB_MEMBER_NOT_FOUND"

    def it_returns_404_when_the_username_does_not_exist(client: TestClient, club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = None

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "USER_NOT_FOUND"

    def it_returns_404_when_the_target_users_record_vanished_after_the_membership_check(
        client: TestClient,
        club_service: AsyncMock,
        club_repo: AsyncMock,
        user_repo: AsyncMock,
        user_service: AsyncMock,
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.get_member_profile.return_value = MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER)
        user_service.find_profile_by_id.return_value = None

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "CLUB_MEMBER_NOT_FOUND"


def describe_remove_club_member():
    def it_returns_204_when_removed(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.remove_member.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}")

        assert response.status_code == 204
        club_service.remove_member.assert_awaited_once_with(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID)

    def it_returns_403_when_the_caller_lacks_sufficient_rank(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.remove_member.side_effect = UnauthorizedClubMemberError("nope")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}")

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_404_when_the_target_is_not_a_member(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.remove_member.side_effect = ClubMemberNotFoundError("not a member")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "CLUB_MEMBER_NOT_FOUND"

    def it_returns_404_when_the_username_does_not_exist(client: TestClient, club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}")

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "USER_NOT_FOUND"

    def it_returns_409_when_the_target_is_a_protected_former_owner(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.remove_member.side_effect = FormerOwnerProtectedError("protected")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}")

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "FORMER_OWNER_PROTECTED"


def describe_change_club_member_role():
    def it_returns_204_when_changed(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.change_member_role.return_value = None

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}/role", json={"role": "ADMIN"})

        assert response.status_code == 204
        club_service.change_member_role.assert_awaited_once_with(
            SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID, MemberRole.ADMIN
        )

    def it_returns_400_when_the_target_is_the_owner(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.change_member_role.side_effect = CannotChangeOwnerRoleError("nope")

        response = client.put(
            f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}/role", json={"role": "MEMBER"}
        )

        assert response.status_code == 400
        assert response.json()["error"]["error_code"] == "CANNOT_CHANGE_OWNER_ROLE"

    def it_returns_403_when_the_caller_is_not_owner(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.change_member_role.side_effect = UnauthorizedClubMemberError("nope")

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}/role", json={"role": "ADMIN"})

        assert response.status_code == 403
        assert response.json()["error"]["error_code"] == "UNAUTHORIZED_CLUB_MEMBER"

    def it_returns_404_when_the_target_is_not_a_member(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.change_member_role.side_effect = ClubMemberNotFoundError("not a member")

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}/role", json={"role": "ADMIN"})

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "CLUB_MEMBER_NOT_FOUND"

    def it_returns_404_when_the_username_does_not_exist(client: TestClient, club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = None

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}/role", json={"role": "ADMIN"})

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "USER_NOT_FOUND"

    def it_returns_409_when_the_target_is_a_protected_former_owner(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.change_member_role.side_effect = FormerOwnerProtectedError("protected")

        response = client.put(
            f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}/role", json={"role": "MEMBER"}
        )

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "FORMER_OWNER_PROTECTED"

    def it_returns_409_when_the_repository_reports_a_conflict(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_service.change_member_role.side_effect = MemberRoleChangeConflictError("stale")

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}/role", json={"role": "ADMIN"})

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "MEMBER_ROLE_CHANGE_CONFLICT"

    def it_returns_422_when_the_requested_role_is_owner(client: TestClient, club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/members/{SOME_TARGET_USERNAME}/role", json={"role": "OWNER"})

        assert response.status_code == 422


def describe_create_ownership_transfer():
    def it_returns_201_with_the_reclaim_deadline_when_transferred(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        deadline = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)
        club_service.transfer_ownership.return_value = deadline

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers",
            json={"new_owner_username": SOME_TARGET_USERNAME},
        )

        assert response.status_code == 201
        assert response.json()["reclaim_deadline"] == "2026-07-13T12:00:00Z"
        club_service.transfer_ownership.assert_awaited_once_with(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_USERNAME)

    def it_returns_400_when_the_target_is_the_caller(client: TestClient, club_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.transfer_ownership.side_effect = CannotTransferOwnershipToSelfError("nope")

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers",
            json={"new_owner_username": SOME_TARGET_USERNAME},
        )

        assert response.status_code == 400
        assert response.json()["error"]["error_code"] == "CANNOT_TRANSFER_OWNERSHIP_TO_SELF"

    def it_returns_403_when_the_caller_is_not_owner(client: TestClient, club_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.transfer_ownership.side_effect = UnauthorizedClubMemberError("nope")

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers",
            json={"new_owner_username": SOME_TARGET_USERNAME},
        )

        assert response.status_code == 403

    def it_returns_404_when_the_target_is_not_a_member(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.transfer_ownership.side_effect = ClubMemberNotFoundError("not a member")

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers",
            json={"new_owner_username": SOME_TARGET_USERNAME},
        )

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "CLUB_MEMBER_NOT_FOUND"

    def it_returns_404_when_the_username_does_not_exist(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.transfer_ownership.side_effect = UserNotFoundError("no such user")

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers",
            json={"new_owner_username": SOME_TARGET_USERNAME},
        )

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "USER_NOT_FOUND"

    def it_returns_409_when_the_new_owner_cooldown_is_active(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.transfer_ownership.side_effect = OwnershipTransferCooldownError("too soon")

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers",
            json={"new_owner_username": SOME_TARGET_USERNAME},
        )

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "OWNERSHIP_TRANSFER_COOLDOWN"

    def it_returns_409_when_the_repository_reports_a_conflict(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.transfer_ownership.side_effect = OwnershipTransferConflictError("stale")

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers",
            json={"new_owner_username": SOME_TARGET_USERNAME},
        )

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "OWNERSHIP_TRANSFER_CONFLICT"

    def it_returns_429_once_the_rate_limit_is_exceeded(
        client: TestClient, club_repo: AsyncMock, redis_client: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        redis_client.incr.return_value = 999
        redis_client.ttl.return_value = 30

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers",
            json={"new_owner_username": SOME_TARGET_USERNAME},
        )

        assert response.status_code == 429
        assert response.json()["error"]["error_code"] == "RATE_LIMIT_EXCEEDED"
        assert response.headers["Retry-After"] == "30"


def describe_reclaim_club_ownership():
    def it_returns_204_when_reclaimed(client: TestClient, club_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.reclaim_ownership.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers/current")

        assert response.status_code == 204
        club_service.reclaim_ownership.assert_awaited_once_with(SOME_CLUB_ID, SOME_OWNER_ID)

    def it_returns_403_when_the_caller_is_not_the_recorded_former_owner(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.reclaim_ownership.side_effect = UnauthorizedClubMemberError("nope")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers/current")

        assert response.status_code == 403

    def it_returns_404_when_the_club_slug_does_not_exist(client: TestClient, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers/current")

        assert response.status_code == 404

    def it_returns_409_when_the_reclaim_window_has_expired(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.reclaim_ownership.side_effect = OwnershipReclaimWindowExpiredError("too late")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers/current")

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "OWNERSHIP_RECLAIM_WINDOW_EXPIRED"

    def it_returns_409_when_the_repository_reports_a_conflict(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.reclaim_ownership.side_effect = OwnershipTransferConflictError("stale")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers/current")

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "OWNERSHIP_TRANSFER_CONFLICT"

    def it_returns_429_once_the_rate_limit_is_exceeded(
        client: TestClient, club_repo: AsyncMock, redis_client: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        redis_client.incr.return_value = 999
        redis_client.ttl.return_value = 15

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}/ownership-transfers/current")

        assert response.status_code == 429
        assert response.json()["error"]["error_code"] == "RATE_LIMIT_EXCEEDED"
        assert response.headers["Retry-After"] == "15"


def describe_dissolve_club():
    def it_returns_204_when_dissolved(client: TestClient, club_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.dissolve_club.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}")

        assert response.status_code == 204
        club_service.dissolve_club.assert_awaited_once_with(SOME_CLUB_ID, SOME_OWNER_ID)

    def it_returns_403_when_the_caller_is_not_the_owner(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.dissolve_club.side_effect = UnauthorizedClubMemberError("nope")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}")

        assert response.status_code == 403

    def it_returns_404_when_the_club_slug_does_not_exist(client: TestClient, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = None

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}")

        assert response.status_code == 404

    def it_returns_409_when_a_former_owner_is_still_protected(
        client: TestClient, club_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        club_service.dissolve_club.side_effect = FormerOwnerProtectedError("still protected")

        response = client.delete(f"/v1/clubs/{SOME_CLUB_SLUG}")

        assert response.status_code == 409
        assert response.json()["error"]["error_code"] == "FORMER_OWNER_PROTECTED"


def describe_create_invite():
    def it_rotates_the_public_link_and_returns_the_new_token(
        client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        invite_service.rotate_public_link.return_value = "new-token"

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/invites", json={"type": "PUBLIC"})

        assert response.status_code == 201
        assert response.json()["invite_token"] == "new-token"
        assert response.headers["Location"] == "/v1/invites/new-token/preview"
        invite_service.create_direct_invite.assert_not_called()

    def it_returns_404_when_the_club_slug_does_not_exist_for_a_public_invite(client: TestClient, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = None

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/invites", json={"type": "PUBLIC"})

        assert response.status_code == 404
        assert response.json()["error"]["error_code"] == "CLUB_NOT_FOUND"

    def it_returns_403_when_the_requester_lacks_permission_for_a_public_invite(
        client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        invite_service.rotate_public_link.side_effect = UnauthorizedClubMemberError("nope")

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/invites", json={"type": "PUBLIC"})

        assert response.status_code == 403

    def it_creates_a_direct_invite_and_returns_the_new_token(
        client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        invite_service.create_direct_invite.return_value = "direct-token"

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/invites", json={"type": "DIRECT", "email": "alice@example.com"}
        )

        assert response.status_code == 201
        assert response.json()["invite_token"] == "direct-token"
        assert response.headers["Location"] == "/v1/invites/direct-token/preview"
        invite_service.rotate_public_link.assert_not_called()

    def it_returns_404_when_the_club_slug_does_not_exist_for_a_direct_invite(client: TestClient, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = None

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/invites", json={"type": "DIRECT", "email": "alice@example.com"}
        )

        assert response.status_code == 404

    def it_returns_422_for_an_invalid_email(client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/invites", json={"type": "DIRECT", "email": "not-an-email"})

        assert response.status_code == 422
        invite_service.create_direct_invite.assert_not_called()

    def it_returns_422_when_a_direct_invite_has_no_email(
        client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/invites", json={"type": "DIRECT"})

        assert response.status_code == 422
        invite_service.create_direct_invite.assert_not_called()

    def it_returns_422_when_a_public_invite_includes_an_email(
        client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID

        response = client.post(
            f"/v1/clubs/{SOME_CLUB_SLUG}/invites", json={"type": "PUBLIC", "email": "alice@example.com"}
        )

        assert response.status_code == 422
        invite_service.rotate_public_link.assert_not_called()


def describe_get_public_invite():
    def it_returns_the_active_public_invite_token(client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        invite_service.get_public_link.return_value = "public-token"

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/invites/public")

        assert response.status_code == 200
        assert response.json() == {"invite_token": "public-token"}

    def it_returns_404_when_the_club_slug_does_not_exist(client: TestClient, club_repo: AsyncMock):
        club_repo.find_id_by_slug.return_value = None

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/invites/public")

        assert response.status_code == 404

    def it_returns_410_when_there_is_no_active_link(
        client: TestClient, invite_service: AsyncMock, club_repo: AsyncMock
    ):
        club_repo.find_id_by_slug.return_value = SOME_CLUB_ID
        invite_service.get_public_link.side_effect = InviteLinkDeactivatedError("gone")

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/invites/public")

        assert response.status_code == 410
        assert response.json()["error"]["error_code"] == "INVITE_LINK_DEACTIVATED"
