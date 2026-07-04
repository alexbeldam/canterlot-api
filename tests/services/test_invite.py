from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.exceptions import (
    ClubNotFoundError,
    DirectInviteIdentityMismatchError,
    InvalidInviteTokenError,
    InviteLinkDeactivatedError,
    UnauthorizedClubMemberError,
)
from canterlot.models.enums import InviteType, UserRole
from canterlot.services.invite import InviteService

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_INVITER_ID = PydanticObjectId("507f1f77bcf86cd799439013")


def _invite(**overrides) -> SimpleNamespace:
    defaults = {
        "id": "shortuuid01",
        "club_id": SOME_CLUB_ID,
        "created_by": None,
        "target_email": None,
        "type": InviteType.PUBLIC,
        "is_active": True,
        "expires_at": None,
    }
    return SimpleNamespace(**{**defaults, **overrides})


def _club() -> SimpleNamespace:
    return SimpleNamespace(id=SOME_CLUB_ID, name="Book Club", join_policy="PUBLIC")


def describe_get_preview_metadata():
    async def it_raises_for_an_unknown_invite(invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock):
        invite_repo.find_by_id.return_value = None
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(InvalidInviteTokenError):
            await service.get_preview_metadata("bad-id")

    async def it_raises_for_a_deactivated_invite(invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock):
        invite_repo.find_by_id.return_value = _invite(is_active=False)
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(InviteLinkDeactivatedError):
            await service.get_preview_metadata("some-id")

    async def it_raises_for_an_expired_invite(invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock):
        invite_repo.find_by_id.return_value = _invite(expires_at=datetime.now(UTC) - timedelta(days=1))
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(InviteLinkDeactivatedError):
            await service.get_preview_metadata("some-id")

    async def it_raises_when_the_target_club_no_longer_exists(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite()
        club_repo.find_by_id.return_value = None
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.get_preview_metadata("some-id")

    async def it_omits_the_inviter_username_when_created_by_is_absent(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite()
        club_repo.find_by_id.return_value = _club()
        service = InviteService(invite_repo, club_repo, user_repo)

        preview = await service.get_preview_metadata("some-id")

        assert preview.invited_by_username is None
        user_repo.find_username_by_id.assert_not_called()

    async def it_resolves_the_inviter_username_when_created_by_is_present(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite(created_by=SOME_INVITER_ID)
        club_repo.find_by_id.return_value = _club()
        user_repo.find_username_by_id.return_value = "inviter_1"
        service = InviteService(invite_repo, club_repo, user_repo)

        preview = await service.get_preview_metadata("some-id")

        assert preview.invited_by_username == "inviter_1"
        user_repo.find_username_by_id.assert_awaited_once_with(SOME_INVITER_ID)


def describe_validate_incoming_invite():
    async def it_raises_for_a_missing_or_inactive_invite(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = None
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(InviteLinkDeactivatedError):
            await service.validate_incoming_invite("bad-id")

    async def it_raises_for_an_expired_invite(invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock):
        invite_repo.find_by_id.return_value = _invite(expires_at=datetime.now(UTC) - timedelta(days=1))
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(InviteLinkDeactivatedError):
            await service.validate_incoming_invite("some-id")

    async def it_raises_when_the_club_no_longer_exists(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite()
        club_repo.find_by_id.return_value = None
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.validate_incoming_invite("some-id")

    async def it_raises_on_a_direct_invite_email_mismatch(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite(type=InviteType.DIRECT, target_email="alice@example.com")
        club_repo.find_by_id.return_value = _club()
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(DirectInviteIdentityMismatchError):
            await service.validate_incoming_invite("some-id", user_email="bob@example.com")

    async def it_raises_on_a_direct_invite_with_no_email_supplied(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite(type=InviteType.DIRECT, target_email="alice@example.com")
        club_repo.find_by_id.return_value = _club()
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(DirectInviteIdentityMismatchError):
            await service.validate_incoming_invite("some-id")

    async def it_accepts_a_direct_invite_with_a_matching_email(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite(type=InviteType.DIRECT, target_email="alice@example.com")
        club_repo.find_by_id.return_value = _club()
        service = InviteService(invite_repo, club_repo, user_repo)

        result = await service.validate_incoming_invite("some-id", user_email="alice@example.com")

        assert result.is_direct is True

    async def it_accepts_a_public_invite_without_requiring_an_email(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite(type=InviteType.PUBLIC)
        club_repo.find_by_id.return_value = _club()
        service = InviteService(invite_repo, club_repo, user_repo)

        result = await service.validate_incoming_invite("some-id")

        assert result.is_direct is False

    async def it_resolves_the_inviter_username_from_created_by(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite(created_by=SOME_INVITER_ID)
        club_repo.find_by_id.return_value = _club()
        user_repo.find_username_by_id.return_value = "inviter_1"
        service = InviteService(invite_repo, club_repo, user_repo)

        result = await service.validate_incoming_invite("some-id")

        assert result.invited_by == "inviter_1"

    async def it_resolves_the_inviter_username_from_invited_by_when_it_exists(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite()
        club_repo.find_by_id.return_value = _club()
        user_repo.exists_by_username.return_value = True
        service = InviteService(invite_repo, club_repo, user_repo)

        result = await service.validate_incoming_invite("some-id", invited_by="referrer_1")

        assert result.invited_by == "referrer_1"

    async def it_ignores_invited_by_when_the_referrer_does_not_exist(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite()
        club_repo.find_by_id.return_value = _club()
        user_repo.exists_by_username.return_value = False
        service = InviteService(invite_repo, club_repo, user_repo)

        result = await service.validate_incoming_invite("some-id", invited_by="ghost")

        assert result.invited_by is None


def describe_rotate_public_link():
    async def it_raises_when_the_requester_lacks_a_privileged_role(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = UserRole.USER
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.rotate_public_link(SOME_CLUB_ID, SOME_USER_ID)

    @pytest.mark.parametrize("role", [UserRole.OWNER, UserRole.ADMIN])
    async def it_deactivates_existing_links_and_issues_a_new_one(
        role: UserRole, invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = role
        invite_repo.save.return_value = _invite(id="new-invite-id")
        service = InviteService(invite_repo, club_repo, user_repo)

        result = await service.rotate_public_link(SOME_CLUB_ID, SOME_USER_ID)

        assert result == "new-invite-id"
        invite_repo.deactivate_all_public_by_club_id.assert_awaited_once_with(SOME_CLUB_ID)


def describe_get_public_link():
    async def it_returns_the_active_public_link_id(invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock):
        invite_repo.find_one_active_public_by_club_id.return_value = _invite(id="public-id")
        service = InviteService(invite_repo, club_repo, user_repo)

        assert await service.get_public_link(SOME_CLUB_ID) == "public-id"

    async def it_raises_when_there_is_no_active_public_link(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_one_active_public_by_club_id.return_value = None
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(InviteLinkDeactivatedError):
            await service.get_public_link(SOME_CLUB_ID)


def describe_create_direct_invite():
    async def it_raises_when_the_issuer_lacks_a_privileged_role(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = None
        service = InviteService(invite_repo, club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.create_direct_invite(SOME_CLUB_ID, SOME_USER_ID, "alice@example.com")

    async def it_issues_a_direct_invite_for_a_privileged_issuer(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = UserRole.OWNER
        invite_repo.save.return_value = _invite(id="direct-invite-id", type=InviteType.DIRECT)
        service = InviteService(invite_repo, club_repo, user_repo)

        result = await service.create_direct_invite(SOME_CLUB_ID, SOME_USER_ID, "alice@example.com")

        assert result == "direct-invite-id"


def describe_register_invite_usage():
    async def it_does_nothing_for_an_unknown_invite(invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock):
        invite_repo.find_by_id.return_value = None
        service = InviteService(invite_repo, club_repo, user_repo)

        await service.register_invite_usage("bad-id")

        invite_repo.increment_uses_count_by_id.assert_not_called()

    async def it_increments_usage_for_a_public_invite_without_deactivating_it(
        invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        invite_repo.find_by_id.return_value = _invite(type=InviteType.PUBLIC)
        service = InviteService(invite_repo, club_repo, user_repo)

        await service.register_invite_usage("some-id")

        invite_repo.increment_uses_count_by_id.assert_awaited_once()
        invite_repo.deactivate_by_id.assert_not_called()

    async def it_burns_a_direct_invite_after_use(invite_repo: AsyncMock, club_repo: AsyncMock, user_repo: AsyncMock):
        invite_repo.find_by_id.return_value = _invite(type=InviteType.DIRECT)
        service = InviteService(invite_repo, club_repo, user_repo)

        await service.register_invite_usage("some-id")

        invite_repo.increment_uses_count_by_id.assert_awaited_once()
        invite_repo.deactivate_by_id.assert_awaited_once()
