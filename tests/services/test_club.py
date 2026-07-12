from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.club import ClubCreateRequest, ClubSettingsUpdateRequest
from canterlot.exceptions import (
    CannotChangeOwnerRoleError,
    CannotTransferOwnershipToSelfError,
    ClubMemberNotFoundError,
    ClubNotFoundError,
    ClubOwnerCannotLeaveError,
    FormerOwnerProtectedError,
    MemberRoleChangeConflictError,
    OwnershipReclaimWindowExpiredError,
    OwnershipTransferConflictError,
    OwnershipTransferCooldownError,
    PendingRequestNotFoundError,
    UnauthorizedClubMemberError,
    UserNotFoundError,
)
from canterlot.models import ClubOnboardingStatus, JoinPolicy, MemberRole
from canterlot.models.club import MemberSchema, PendingApprovalSchema
from canterlot.services.club import ClubService

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_PENDING_ID = PydanticObjectId("507f1f77bcf86cd799439013")
SOME_TARGET_ID = PydanticObjectId("507f1f77bcf86cd799439015")
SOME_TARGET_USERNAME = "carol_3"


def _club(
    join_policy: JoinPolicy = JoinPolicy.PUBLIC,
    members: list[MemberSchema] | None = None,
    banned_users: list[PydanticObjectId] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=SOME_CLUB_ID,
        name="Book Club",
        join_policy=join_policy,
        members=members or [],
        banned_users=banned_users or [],
    )


def describe_create_new_club():
    async def it_saves_a_club_with_the_creator_as_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.exists_by_club_slug.return_value = False
        club_repo.save.side_effect = lambda club: club
        service = ClubService(club_repo, user_repo)

        request = ClubCreateRequest(name="Book Club")
        result = await service.create_new_club(creator_id=SOME_USER_ID, data=request)

        assert result.name == "Book Club"
        assert result.slug
        assert len(result.members) == 1
        assert result.members[0].user_id == SOME_USER_ID
        club_repo.save.assert_awaited_once()


def describe_admit_user():
    async def it_raises_when_the_club_does_not_exist(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

    async def it_short_circuits_when_the_user_is_already_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(members=[MemberSchema(user_id=SOME_USER_ID)])
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.ALREADY_MEMBER
        club_repo.add_member.assert_not_called()
        club_repo.add_to_pending_approvals.assert_not_called()

    async def it_admits_directly_when_the_join_policy_is_public(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.PUBLIC)
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.JOINED
        club_repo.add_member.assert_awaited_once()
        club_repo.add_to_pending_approvals.assert_not_called()

    async def it_admits_directly_for_a_direct_invite_regardless_of_join_policy(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.RESTRICTED)
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID, is_direct=True)

        assert result.status == ClubOnboardingStatus.JOINED
        club_repo.add_member.assert_awaited_once()

    async def it_queues_for_approval_when_the_join_policy_is_restricted(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.RESTRICTED)
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.PENDING_APPROVAL
        club_repo.add_to_pending_approvals.assert_awaited_once_with(SOME_CLUB_ID, SOME_USER_ID)
        club_repo.add_member.assert_not_called()

    async def it_rejects_a_banned_user_joining_via_a_public_link_into_a_public_club(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.PUBLIC, banned_users=[SOME_USER_ID])
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.BANNED
        club_repo.add_member.assert_not_called()
        club_repo.add_to_pending_approvals.assert_not_called()
        club_repo.remove_from_banned_users.assert_not_called()

    async def it_rejects_a_banned_user_joining_via_a_public_link_into_a_restricted_club(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.RESTRICTED, banned_users=[SOME_USER_ID])
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.BANNED
        club_repo.add_member.assert_not_called()
        club_repo.add_to_pending_approvals.assert_not_called()

    async def it_unbans_and_admits_a_banned_user_via_a_direct_invite(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.RESTRICTED, banned_users=[SOME_USER_ID])
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID, is_direct=True)

        assert result.status == ClubOnboardingStatus.JOINED
        club_repo.remove_from_banned_users.assert_awaited_once_with(SOME_CLUB_ID, SOME_USER_ID)
        club_repo.add_member.assert_awaited_once()


def describe_get_preferred_languages():
    async def it_returns_the_clubs_preferred_languages_for_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.get_preferred_languages_by_id.return_value = ["en", "pt-BR"]
        service = ClubService(club_repo, user_repo)

        result = await service.get_preferred_languages(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result == ["en", "pt-BR"]

    async def it_raises_when_the_user_is_not_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.exists_by_club_id_and_member_user_id.return_value = False
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.get_preferred_languages(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        club_repo.get_preferred_languages_by_id.assert_not_called()

    async def it_propagates_a_club_not_found_error_from_the_repository(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.get_preferred_languages_by_id.side_effect = ClubNotFoundError("not found")
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.get_preferred_languages(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)


def describe_get_club_by_slug():
    async def it_returns_the_club_when_found(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_slug.return_value = _club()
        service = ClubService(club_repo, user_repo)

        result = await service.get_club_by_slug("book-club")

        assert result.name == "Book Club"

    async def it_raises_when_the_slug_does_not_resolve(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_slug.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.get_club_by_slug("missing-club")


def describe_get_member_role():
    async def it_delegates_to_the_repository(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.ADMIN
        service = ClubService(club_repo, user_repo)

        result = await service.get_member_role(SOME_CLUB_ID, SOME_USER_ID)

        assert result == MemberRole.ADMIN
        club_repo.find_member_role_by_club_id_and_user_id.assert_awaited_once_with(SOME_CLUB_ID, SOME_USER_ID)

    async def it_returns_none_when_the_caller_is_not_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = None
        service = ClubService(club_repo, user_repo)

        result = await service.get_member_role(SOME_CLUB_ID, SOME_USER_ID)

        assert result is None


def describe_resolve_member_usernames():
    async def it_delegates_to_the_bulk_username_lookup(club_repo: AsyncMock, user_repo: AsyncMock):
        user_repo.find_usernames_by_ids.return_value = {SOME_USER_ID: "alice_1"}
        service = ClubService(club_repo, user_repo)

        result = await service.resolve_member_usernames([MemberSchema(user_id=SOME_USER_ID)])

        assert result == {SOME_USER_ID: "alice_1"}
        user_repo.find_usernames_by_ids.assert_awaited_once_with([SOME_USER_ID])


def describe_get_club_view():
    def _club_model(with_pending: bool = False) -> SimpleNamespace:
        pending = [PendingApprovalSchema(user_id=SOME_PENDING_ID)] if with_pending else []
        return SimpleNamespace(
            id=SOME_CLUB_ID,
            members=[MemberSchema(user_id=SOME_USER_ID)],
            pending_approvals=pending,
        )

    async def it_omits_pending_usernames_for_a_plain_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_slug.return_value = _club_model()
        club_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.MEMBER
        user_repo.find_usernames_by_ids.return_value = {SOME_USER_ID: "alice_1"}
        service = ClubService(club_repo, user_repo)

        view = await service.get_club_view("book-club", SOME_USER_ID)

        assert view.viewer_role == MemberRole.MEMBER
        assert view.pending_usernames is None
        user_repo.find_usernames_by_ids.assert_awaited_once_with([SOME_USER_ID])

    async def it_raises_when_the_viewer_is_not_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_slug.return_value = _club_model()
        club_repo.find_member_role_by_club_id_and_user_id.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.get_club_view("book-club", SOME_USER_ID)

        user_repo.find_usernames_by_ids.assert_not_called()

    async def it_resolves_pending_usernames_for_an_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_slug.return_value = _club_model(with_pending=True)
        club_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.OWNER
        user_repo.find_usernames_by_ids.side_effect = [
            {SOME_USER_ID: "alice_1"},
            {SOME_PENDING_ID: "bob_2"},
        ]
        service = ClubService(club_repo, user_repo)

        view = await service.get_club_view("book-club", SOME_USER_ID)

        assert view.pending_usernames == {SOME_PENDING_ID: "bob_2"}

    async def it_resolves_pending_usernames_for_an_admin(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_slug.return_value = _club_model(with_pending=True)
        club_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.ADMIN
        user_repo.find_usernames_by_ids.side_effect = [
            {SOME_USER_ID: "alice_1"},
            {SOME_PENDING_ID: "bob_2"},
        ]
        service = ClubService(club_repo, user_repo)

        view = await service.get_club_view("book-club", SOME_USER_ID)

        assert view.pending_usernames == {SOME_PENDING_ID: "bob_2"}

    async def it_raises_when_the_slug_does_not_resolve(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_slug.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.get_club_view("missing-club", SOME_USER_ID)


def describe_review_pending_request():
    SOME_REVIEWER_ID = PydanticObjectId("507f1f77bcf86cd799439014")

    async def it_raises_when_the_reviewer_is_not_owner_or_admin(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.MEMBER
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.review_pending_request(SOME_CLUB_ID, SOME_REVIEWER_ID, SOME_PENDING_ID, approve=True)

        club_repo.exists_by_club_id_and_pending_user_id.assert_not_called()

    async def it_raises_when_the_reviewer_is_not_a_member_at_all(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.review_pending_request(SOME_CLUB_ID, SOME_REVIEWER_ID, SOME_PENDING_ID, approve=True)

    async def it_raises_when_the_target_user_has_no_pending_request(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.OWNER
        club_repo.exists_by_club_id_and_pending_user_id.return_value = False
        service = ClubService(club_repo, user_repo)

        with pytest.raises(PendingRequestNotFoundError):
            await service.review_pending_request(SOME_CLUB_ID, SOME_REVIEWER_ID, SOME_PENDING_ID, approve=True)

        club_repo.add_member.assert_not_called()
        club_repo.remove_from_pending_approvals.assert_not_called()

    async def it_admits_the_user_as_a_member_when_approved(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.ADMIN
        club_repo.exists_by_club_id_and_pending_user_id.return_value = True
        service = ClubService(club_repo, user_repo)

        await service.review_pending_request(SOME_CLUB_ID, SOME_REVIEWER_ID, SOME_PENDING_ID, approve=True)

        added_member = club_repo.add_member.call_args.args[1]
        assert added_member.user_id == SOME_PENDING_ID
        assert added_member.role == MemberRole.MEMBER
        club_repo.remove_from_pending_approvals.assert_awaited_once_with(SOME_CLUB_ID, SOME_PENDING_ID)

    async def it_only_dequeues_the_user_when_rejected(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.OWNER
        club_repo.exists_by_club_id_and_pending_user_id.return_value = True
        service = ClubService(club_repo, user_repo)

        await service.review_pending_request(SOME_CLUB_ID, SOME_REVIEWER_ID, SOME_PENDING_ID, approve=False)

        club_repo.add_member.assert_not_called()
        club_repo.remove_from_pending_approvals.assert_awaited_once_with(SOME_CLUB_ID, SOME_PENDING_ID)


def describe_transfer_ownership():
    def _club(
        members: list[MemberSchema],
        ownership_transferred_at: datetime | None = None,
        protected_former_owner_id: PydanticObjectId | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            members=members,
            ownership_transferred_at=ownership_transferred_at,
            protected_former_owner_id=protected_former_owner_id,
        )

    async def it_raises_when_the_target_username_does_not_resolve_to_any_user(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        user_repo.find_id_by_username.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UserNotFoundError):
            await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

        club_repo.find_by_id.assert_not_called()

    async def it_raises_when_the_club_does_not_exist(club_repo: AsyncMock, user_repo: AsyncMock):
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_repo.find_by_id.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

    async def it_raises_when_the_target_is_the_caller(club_repo: AsyncMock, user_repo: AsyncMock):
        user_repo.find_id_by_username.return_value = SOME_USER_ID
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(CannotTransferOwnershipToSelfError):
            await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

        club_repo.transfer_ownership.assert_not_called()

    async def it_raises_when_the_caller_is_not_a_member_at_all(club_repo: AsyncMock, user_repo: AsyncMock):
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

    async def it_raises_when_the_caller_is_not_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_USER_ID, role=MemberRole.ADMIN),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ]
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

    async def it_raises_when_the_target_is_not_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubMemberNotFoundError):
            await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

    async def it_raises_when_the_new_owner_cooldown_is_still_active(club_repo: AsyncMock, user_repo: AsyncMock):
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=29),
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(OwnershipTransferCooldownError):
            await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

        club_repo.transfer_ownership.assert_not_called()

    async def it_exempts_a_transfer_back_to_the_recorded_former_owner_from_the_cooldown(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=1),
            protected_former_owner_id=SOME_TARGET_ID,
        )
        club_repo.transfer_ownership.return_value = True
        service = ClubService(club_repo, user_repo)

        await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

        club_repo.transfer_ownership.assert_awaited_once()

    async def it_allows_a_transfer_once_the_cooldown_has_elapsed(club_repo: AsyncMock, user_repo: AsyncMock):
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=31),
        )
        club_repo.transfer_ownership.return_value = True
        service = ClubService(club_repo, user_repo)

        await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

        club_repo.transfer_ownership.assert_awaited_once()

    async def it_raises_a_conflict_when_the_repository_reports_no_match(club_repo: AsyncMock, user_repo: AsyncMock):
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ]
        )
        club_repo.transfer_ownership.return_value = False
        service = ClubService(club_repo, user_repo)

        with pytest.raises(OwnershipTransferConflictError):
            await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

    async def it_transfers_ownership_successfully_and_returns_the_reclaim_deadline(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        user_repo.find_id_by_username.return_value = SOME_TARGET_ID
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ]
        )
        club_repo.transfer_ownership.return_value = True
        service = ClubService(club_repo, user_repo)

        before = datetime.now(UTC)
        reclaim_deadline = await service.transfer_ownership(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_USERNAME)

        club_repo.transfer_ownership.assert_awaited_once_with(SOME_CLUB_ID, SOME_USER_ID, SOME_TARGET_ID, ANY)
        assert timedelta(hours=23) < reclaim_deadline - before < timedelta(hours=25)


def describe_reclaim_ownership():
    SOME_FORMER_OWNER_ID = PydanticObjectId("507f1f77bcf86cd799439016")
    SOME_CURRENT_OWNER_ID = PydanticObjectId("507f1f77bcf86cd799439017")

    def _club(
        protected_former_owner_id: PydanticObjectId | None,
        ownership_transferred_at: datetime | None,
        current_owner_id: PydanticObjectId = SOME_CURRENT_OWNER_ID,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            protected_former_owner_id=protected_former_owner_id,
            ownership_transferred_at=ownership_transferred_at,
            members=[MemberSchema(user_id=current_owner_id, role=MemberRole.OWNER)],
        )

    async def it_raises_when_the_club_does_not_exist(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.reclaim_ownership(SOME_CLUB_ID, SOME_FORMER_OWNER_ID)

    async def it_raises_when_the_caller_is_not_the_recorded_former_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            protected_former_owner_id=SOME_CURRENT_OWNER_ID,
            ownership_transferred_at=datetime.now(UTC),
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.reclaim_ownership(SOME_CLUB_ID, SOME_FORMER_OWNER_ID)

        club_repo.reclaim_ownership.assert_not_called()

    async def it_raises_a_conflict_when_the_ownership_state_is_inconsistent(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = SimpleNamespace(
            protected_former_owner_id=SOME_FORMER_OWNER_ID,
            ownership_transferred_at=None,
            members=[MemberSchema(user_id=SOME_CURRENT_OWNER_ID, role=MemberRole.OWNER)],
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(OwnershipTransferConflictError):
            await service.reclaim_ownership(SOME_CLUB_ID, SOME_FORMER_OWNER_ID)

        club_repo.reclaim_ownership.assert_not_called()

    async def it_raises_when_the_reclaim_window_has_elapsed(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            protected_former_owner_id=SOME_FORMER_OWNER_ID,
            ownership_transferred_at=datetime.now(UTC) - timedelta(hours=25),
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(OwnershipReclaimWindowExpiredError):
            await service.reclaim_ownership(SOME_CLUB_ID, SOME_FORMER_OWNER_ID)

        club_repo.reclaim_ownership.assert_not_called()

    async def it_reclaims_ownership_within_the_window(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            protected_former_owner_id=SOME_FORMER_OWNER_ID,
            ownership_transferred_at=datetime.now(UTC) - timedelta(hours=23),
        )
        club_repo.reclaim_ownership.return_value = True
        service = ClubService(club_repo, user_repo)

        await service.reclaim_ownership(SOME_CLUB_ID, SOME_FORMER_OWNER_ID)

        club_repo.reclaim_ownership.assert_awaited_once_with(SOME_CLUB_ID, SOME_FORMER_OWNER_ID, SOME_CURRENT_OWNER_ID)

    async def it_raises_a_conflict_when_the_repository_reports_no_match(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            protected_former_owner_id=SOME_FORMER_OWNER_ID,
            ownership_transferred_at=datetime.now(UTC),
        )
        club_repo.reclaim_ownership.return_value = False
        service = ClubService(club_repo, user_repo)

        with pytest.raises(OwnershipTransferConflictError):
            await service.reclaim_ownership(SOME_CLUB_ID, SOME_FORMER_OWNER_ID)


def describe_remove_member():
    SOME_REMOVER_ID = PydanticObjectId("507f1f77bcf86cd799439018")

    def _club(
        members: list[MemberSchema],
        ownership_transferred_at: datetime | None = None,
        protected_former_owner_id: PydanticObjectId | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            members=members,
            ownership_transferred_at=ownership_transferred_at,
            protected_former_owner_id=protected_former_owner_id,
        )

    async def it_raises_when_the_club_does_not_exist(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.remove_member(SOME_CLUB_ID, SOME_REMOVER_ID, SOME_TARGET_ID)

    async def it_raises_when_the_remover_is_not_a_member_at_all(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.remove_member(SOME_CLUB_ID, SOME_REMOVER_ID, SOME_TARGET_ID)

        club_repo.remove_and_ban_member.assert_not_called()

    async def it_raises_when_the_remover_is_a_plain_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_REMOVER_ID, role=MemberRole.MEMBER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ]
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.remove_member(SOME_CLUB_ID, SOME_REMOVER_ID, SOME_TARGET_ID)

    async def it_raises_when_the_target_is_not_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_REMOVER_ID, role=MemberRole.OWNER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubMemberNotFoundError):
            await service.remove_member(SOME_CLUB_ID, SOME_REMOVER_ID, SOME_TARGET_ID)

    async def it_raises_when_an_admin_targets_another_admin(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_REMOVER_ID, role=MemberRole.ADMIN),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.ADMIN),
            ]
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.remove_member(SOME_CLUB_ID, SOME_REMOVER_ID, SOME_TARGET_ID)

        club_repo.remove_and_ban_member.assert_not_called()

    async def it_raises_when_an_admin_targets_the_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_REMOVER_ID, role=MemberRole.ADMIN),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.OWNER),
            ]
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.remove_member(SOME_CLUB_ID, SOME_REMOVER_ID, SOME_TARGET_ID)

    async def it_raises_when_the_target_is_a_protected_former_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_REMOVER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.ADMIN),
            ],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=29),
            protected_former_owner_id=SOME_TARGET_ID,
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(FormerOwnerProtectedError):
            await service.remove_member(SOME_CLUB_ID, SOME_REMOVER_ID, SOME_TARGET_ID)

        club_repo.remove_and_ban_member.assert_not_called()

    async def it_allows_removal_of_the_former_owner_once_the_window_elapses(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_REMOVER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.ADMIN),
            ],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=31),
            protected_former_owner_id=SOME_TARGET_ID,
        )
        service = ClubService(club_repo, user_repo)

        await service.remove_member(SOME_CLUB_ID, SOME_REMOVER_ID, SOME_TARGET_ID)

        club_repo.remove_and_ban_member.assert_awaited_once_with(SOME_CLUB_ID, SOME_TARGET_ID)

    async def it_removes_and_bans_an_admin_when_the_owner_is_the_remover(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_REMOVER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.ADMIN),
            ]
        )
        service = ClubService(club_repo, user_repo)

        await service.remove_member(SOME_CLUB_ID, SOME_REMOVER_ID, SOME_TARGET_ID)

        club_repo.remove_and_ban_member.assert_awaited_once_with(SOME_CLUB_ID, SOME_TARGET_ID)

    async def it_removes_and_bans_a_member_when_an_admin_is_the_remover(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_REMOVER_ID, role=MemberRole.ADMIN),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ]
        )
        service = ClubService(club_repo, user_repo)

        await service.remove_member(SOME_CLUB_ID, SOME_REMOVER_ID, SOME_TARGET_ID)

        club_repo.remove_and_ban_member.assert_awaited_once_with(SOME_CLUB_ID, SOME_TARGET_ID)


def describe_change_member_role():
    SOME_OWNER_ID = PydanticObjectId("507f1f77bcf86cd799439019")

    def _club(
        members: list[MemberSchema],
        ownership_transferred_at: datetime | None = None,
        protected_former_owner_id: PydanticObjectId | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            members=members,
            ownership_transferred_at=ownership_transferred_at,
            protected_former_owner_id=protected_former_owner_id,
        )

    async def it_raises_when_the_club_does_not_exist(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.change_member_role(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID, MemberRole.ADMIN)

    async def it_raises_when_the_caller_is_not_a_member_at_all(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.change_member_role(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID, MemberRole.ADMIN)

        club_repo.change_member_role.assert_not_called()

    async def it_raises_when_the_caller_is_an_admin_not_the_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.ADMIN),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ]
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.change_member_role(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID, MemberRole.ADMIN)

    async def it_raises_when_the_target_is_not_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubMemberNotFoundError):
            await service.change_member_role(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID, MemberRole.ADMIN)

    async def it_raises_when_the_target_is_the_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.OWNER),
            ]
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(CannotChangeOwnerRoleError):
            await service.change_member_role(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID, MemberRole.MEMBER)

        club_repo.change_member_role.assert_not_called()

    async def it_raises_when_the_target_is_a_protected_former_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.ADMIN),
            ],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=29),
            protected_former_owner_id=SOME_TARGET_ID,
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(FormerOwnerProtectedError):
            await service.change_member_role(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID, MemberRole.MEMBER)

        club_repo.change_member_role.assert_not_called()

    async def it_allows_demotion_of_the_former_owner_once_the_window_elapses(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.ADMIN),
            ],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=31),
            protected_former_owner_id=SOME_TARGET_ID,
        )
        club_repo.change_member_role.return_value = True
        service = ClubService(club_repo, user_repo)

        await service.change_member_role(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID, MemberRole.MEMBER)

        club_repo.change_member_role.assert_awaited_once_with(SOME_CLUB_ID, SOME_TARGET_ID, MemberRole.MEMBER)

    async def it_raises_when_the_repository_reports_a_conflict(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ]
        )
        club_repo.change_member_role.return_value = False
        service = ClubService(club_repo, user_repo)

        with pytest.raises(MemberRoleChangeConflictError):
            await service.change_member_role(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID, MemberRole.ADMIN)

    async def it_changes_the_role_when_the_owner_promotes_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [
                MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER),
            ]
        )
        club_repo.change_member_role.return_value = True
        service = ClubService(club_repo, user_repo)

        await service.change_member_role(SOME_CLUB_ID, SOME_OWNER_ID, SOME_TARGET_ID, MemberRole.ADMIN)

        club_repo.change_member_role.assert_awaited_once_with(SOME_CLUB_ID, SOME_TARGET_ID, MemberRole.ADMIN)


def describe_update_settings():
    def _club(members: list[MemberSchema], slug: str = "book-club") -> SimpleNamespace:
        return SimpleNamespace(members=members, slug=slug, name="Book Club")

    async def it_raises_when_the_club_does_not_exist(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.update_settings(
                SOME_CLUB_ID, SOME_USER_ID, ClubSettingsUpdateRequest(allow_suggestions=False)
            )

    async def it_raises_when_the_caller_is_not_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.update_settings(
                SOME_CLUB_ID, SOME_USER_ID, ClubSettingsUpdateRequest(allow_suggestions=False)
            )

        club_repo.update_settings.assert_not_called()

    async def it_raises_when_the_caller_is_a_plain_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.MEMBER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.update_settings(
                SOME_CLUB_ID, SOME_USER_ID, ClubSettingsUpdateRequest(allow_suggestions=False)
            )

        club_repo.update_settings.assert_not_called()

    @pytest.mark.parametrize("role", [MemberRole.OWNER, MemberRole.ADMIN])
    async def it_updates_only_the_provided_fields_for_owner_and_admin(
        role: MemberRole, club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=role)])
        club_repo.update_settings.return_value = True
        service = ClubService(club_repo, user_repo)

        result = await service.update_settings(
            SOME_CLUB_ID, SOME_USER_ID, ClubSettingsUpdateRequest(allow_suggestions=False)
        )

        assert result.allow_suggestions is False
        assert result.slug == "book-club"
        club_repo.update_settings.assert_awaited_once_with(
            SOME_CLUB_ID,
            name=None,
            slug=None,
            description=None,
            join_policy=None,
            allow_suggestions=False,
            preferred_languages=None,
        )
        club_repo.exists_by_club_slug.assert_not_called()

    async def it_raises_when_the_repository_reports_no_match(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)])
        club_repo.update_settings.return_value = False
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.update_settings(
                SOME_CLUB_ID, SOME_USER_ID, ClubSettingsUpdateRequest(allow_suggestions=False)
            )

    async def it_regenerates_the_slug_when_the_name_changes(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)])
        club_repo.update_settings.return_value = True
        club_repo.exists_by_club_slug.return_value = False
        service = ClubService(club_repo, user_repo)

        result = await service.update_settings(
            SOME_CLUB_ID, SOME_USER_ID, ClubSettingsUpdateRequest(name="Renamed Club")
        )

        assert result.name == "Renamed Club"
        assert result.slug == "renamed-club"
        club_repo.update_settings.assert_awaited_once_with(
            SOME_CLUB_ID,
            name="Renamed Club",
            slug="renamed-club",
            description=None,
            join_policy=None,
            allow_suggestions=None,
            preferred_languages=None,
        )

    async def it_suffixes_the_slug_when_the_base_slug_is_taken(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)])
        club_repo.update_settings.return_value = True
        club_repo.exists_by_club_slug.side_effect = [True, False]
        service = ClubService(club_repo, user_repo)

        result = await service.update_settings(
            SOME_CLUB_ID, SOME_USER_ID, ClubSettingsUpdateRequest(name="Renamed Club")
        )

        assert result.slug != "renamed-club"
        assert result.slug.startswith("renamed-cl")

    async def it_keeps_the_same_slug_when_the_name_is_resubmitted_unchanged(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)])
        club_repo.update_settings.return_value = True
        service = ClubService(club_repo, user_repo)

        result = await service.update_settings(SOME_CLUB_ID, SOME_USER_ID, ClubSettingsUpdateRequest(name="Book Club"))

        assert result.slug == "book-club"
        club_repo.exists_by_club_slug.assert_not_called()

    async def it_keeps_a_suffixed_slug_untouched_when_the_name_is_resubmitted_unchanged(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_by_id.return_value = _club(
            [MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)], slug="book-club-a1b2c"
        )
        club_repo.update_settings.return_value = True
        service = ClubService(club_repo, user_repo)

        result = await service.update_settings(SOME_CLUB_ID, SOME_USER_ID, ClubSettingsUpdateRequest(name="Book Club"))

        assert result.slug == "book-club-a1b2c"
        club_repo.exists_by_club_slug.assert_not_called()
        club_repo.update_settings.assert_awaited_once_with(
            SOME_CLUB_ID,
            name="Book Club",
            slug=None,
            description=None,
            join_policy=None,
            allow_suggestions=None,
            preferred_languages=None,
        )


def describe_leave_club():
    def _club(
        members: list[MemberSchema],
        ownership_transferred_at: datetime | None = None,
        protected_former_owner_id: PydanticObjectId | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            members=members,
            ownership_transferred_at=ownership_transferred_at,
            protected_former_owner_id=protected_former_owner_id,
        )

    async def it_raises_when_the_club_does_not_exist(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.leave_club(SOME_CLUB_ID, SOME_USER_ID)

    async def it_raises_when_the_caller_is_not_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.MEMBER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.leave_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.remove_member.assert_not_called()

    async def it_raises_when_the_caller_is_the_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubOwnerCannotLeaveError):
            await service.leave_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.remove_member.assert_not_called()

    async def it_raises_when_the_caller_is_a_protected_former_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [MemberSchema(user_id=SOME_USER_ID, role=MemberRole.ADMIN)],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=29),
            protected_former_owner_id=SOME_USER_ID,
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(FormerOwnerProtectedError):
            await service.leave_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.remove_member.assert_not_called()

    async def it_allows_leaving_once_the_former_owner_protection_window_elapses(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_by_id.return_value = _club(
            [MemberSchema(user_id=SOME_USER_ID, role=MemberRole.ADMIN)],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=31),
            protected_former_owner_id=SOME_USER_ID,
        )
        service = ClubService(club_repo, user_repo)

        await service.leave_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.remove_member.assert_awaited_once_with(SOME_CLUB_ID, SOME_USER_ID)

    async def it_removes_a_plain_member_who_leaves_voluntarily(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.MEMBER)])
        service = ClubService(club_repo, user_repo)

        await service.leave_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.remove_member.assert_awaited_once_with(SOME_CLUB_ID, SOME_USER_ID)
        club_repo.remove_and_ban_member.assert_not_called()


def describe_dissolve_club():
    def _club(
        members: list[MemberSchema],
        ownership_transferred_at: datetime | None = None,
        protected_former_owner_id: PydanticObjectId | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            members=members,
            ownership_transferred_at=ownership_transferred_at,
            protected_former_owner_id=protected_former_owner_id,
        )

    async def it_raises_when_the_club_does_not_exist(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = None
        service = ClubService(club_repo, user_repo)

        with pytest.raises(ClubNotFoundError):
            await service.dissolve_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.delete.assert_not_called()

    async def it_raises_when_the_caller_is_not_a_member(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_TARGET_ID, role=MemberRole.OWNER)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.dissolve_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.delete.assert_not_called()

    async def it_raises_when_the_caller_is_not_the_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.ADMIN)])
        service = ClubService(club_repo, user_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.dissolve_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.delete.assert_not_called()

    async def it_raises_when_a_former_owner_is_still_protected(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(
            [MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=29),
            protected_former_owner_id=SOME_TARGET_ID,
        )
        service = ClubService(club_repo, user_repo)

        with pytest.raises(FormerOwnerProtectedError):
            await service.dissolve_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.delete.assert_not_called()

    async def it_allows_dissolution_once_the_former_owner_protection_window_elapses(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_by_id.return_value = _club(
            [MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)],
            ownership_transferred_at=datetime.now(UTC) - timedelta(days=31),
            protected_former_owner_id=SOME_TARGET_ID,
        )
        service = ClubService(club_repo, user_repo)

        await service.dissolve_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.delete.assert_awaited_once_with(SOME_CLUB_ID)

    async def it_dissolves_the_club_when_the_caller_is_the_owner(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club([MemberSchema(user_id=SOME_USER_ID, role=MemberRole.OWNER)])
        service = ClubService(club_repo, user_repo)

        await service.dissolve_club(SOME_CLUB_ID, SOME_USER_ID)

        club_repo.delete.assert_awaited_once_with(SOME_CLUB_ID)
