from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.club import ClubCreateRequest
from canterlot.exceptions import ClubNotFoundError, PendingRequestNotFoundError, UnauthorizedClubMemberError
from canterlot.models import ClubOnboardingStatus, JoinPolicy, UserRole
from canterlot.models.club import MemberSchema, PendingApprovalSchema
from canterlot.services.club import ClubService

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_PENDING_ID = PydanticObjectId("507f1f77bcf86cd799439013")


def _club(join_policy: JoinPolicy = JoinPolicy.PUBLIC) -> SimpleNamespace:
    return SimpleNamespace(id=SOME_CLUB_ID, name="Book Club", join_policy=join_policy)


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
        club_repo.find_by_id.return_value = _club()
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.ALREADY_MEMBER
        club_repo.add_member.assert_not_called()
        club_repo.add_to_pending_approvals.assert_not_called()

    async def it_admits_directly_when_the_join_policy_is_public(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.PUBLIC)
        club_repo.exists_by_club_id_and_member_user_id.return_value = False
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.JOINED
        club_repo.add_member.assert_awaited_once()
        club_repo.add_to_pending_approvals.assert_not_called()

    async def it_admits_directly_for_a_direct_invite_regardless_of_join_policy(
        club_repo: AsyncMock, user_repo: AsyncMock
    ):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.RESTRICTED)
        club_repo.exists_by_club_id_and_member_user_id.return_value = False
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID, is_direct=True)

        assert result.status == ClubOnboardingStatus.JOINED
        club_repo.add_member.assert_awaited_once()

    async def it_queues_for_approval_when_the_join_policy_is_restricted(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.RESTRICTED)
        club_repo.exists_by_club_id_and_member_user_id.return_value = False
        service = ClubService(club_repo, user_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.PENDING_APPROVAL
        club_repo.add_to_pending_approvals.assert_awaited_once_with(SOME_CLUB_ID, SOME_USER_ID)
        club_repo.add_member.assert_not_called()


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
        club_repo.find_member_role_by_club_id_and_user_id.return_value = UserRole.ADMIN
        service = ClubService(club_repo, user_repo)

        result = await service.get_member_role(SOME_CLUB_ID, SOME_USER_ID)

        assert result == UserRole.ADMIN
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
        club_repo.find_member_role_by_club_id_and_user_id.return_value = UserRole.MEMBER
        user_repo.find_usernames_by_ids.return_value = {SOME_USER_ID: "alice_1"}
        service = ClubService(club_repo, user_repo)

        view = await service.get_club_view("book-club", SOME_USER_ID)

        assert view.viewer_role == UserRole.MEMBER
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
        club_repo.find_member_role_by_club_id_and_user_id.return_value = UserRole.OWNER
        user_repo.find_usernames_by_ids.side_effect = [
            {SOME_USER_ID: "alice_1"},
            {SOME_PENDING_ID: "bob_2"},
        ]
        service = ClubService(club_repo, user_repo)

        view = await service.get_club_view("book-club", SOME_USER_ID)

        assert view.pending_usernames == {SOME_PENDING_ID: "bob_2"}

    async def it_resolves_pending_usernames_for_an_admin(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_by_slug.return_value = _club_model(with_pending=True)
        club_repo.find_member_role_by_club_id_and_user_id.return_value = UserRole.ADMIN
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
        club_repo.find_member_role_by_club_id_and_user_id.return_value = UserRole.MEMBER
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
        club_repo.find_member_role_by_club_id_and_user_id.return_value = UserRole.OWNER
        club_repo.exists_by_club_id_and_pending_user_id.return_value = False
        service = ClubService(club_repo, user_repo)

        with pytest.raises(PendingRequestNotFoundError):
            await service.review_pending_request(SOME_CLUB_ID, SOME_REVIEWER_ID, SOME_PENDING_ID, approve=True)

        club_repo.add_member.assert_not_called()
        club_repo.remove_from_pending_approvals.assert_not_called()

    async def it_admits_the_user_as_a_member_when_approved(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = UserRole.ADMIN
        club_repo.exists_by_club_id_and_pending_user_id.return_value = True
        service = ClubService(club_repo, user_repo)

        await service.review_pending_request(SOME_CLUB_ID, SOME_REVIEWER_ID, SOME_PENDING_ID, approve=True)

        added_member = club_repo.add_member.call_args.args[1]
        assert added_member.user_id == SOME_PENDING_ID
        assert added_member.role == UserRole.MEMBER
        club_repo.remove_from_pending_approvals.assert_awaited_once_with(SOME_CLUB_ID, SOME_PENDING_ID)

    async def it_only_dequeues_the_user_when_rejected(club_repo: AsyncMock, user_repo: AsyncMock):
        club_repo.find_member_role_by_club_id_and_user_id.return_value = UserRole.OWNER
        club_repo.exists_by_club_id_and_pending_user_id.return_value = True
        service = ClubService(club_repo, user_repo)

        await service.review_pending_request(SOME_CLUB_ID, SOME_REVIEWER_ID, SOME_PENDING_ID, approve=False)

        club_repo.add_member.assert_not_called()
        club_repo.remove_from_pending_approvals.assert_awaited_once_with(SOME_CLUB_ID, SOME_PENDING_ID)
