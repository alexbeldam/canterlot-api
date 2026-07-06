from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.club import ClubCreateRequest
from canterlot.exceptions import ClubNotFoundError, UnauthorizedClubMemberError
from canterlot.models import ClubOnboardingStatus, JoinPolicy
from canterlot.services.club import ClubService

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439012")


def _club(join_policy: JoinPolicy = JoinPolicy.PUBLIC) -> SimpleNamespace:
    return SimpleNamespace(id=SOME_CLUB_ID, name="Book Club", join_policy=join_policy)


def describe_create_new_club():
    async def it_saves_a_club_with_the_creator_as_owner(club_repo: AsyncMock):
        club_repo.exists_by_club_slug.return_value = False
        club_repo.save.side_effect = lambda club: club
        service = ClubService(club_repo)

        request = ClubCreateRequest(name="Book Club")
        result = await service.create_new_club(creator_id=SOME_USER_ID, data=request)

        assert result.name == "Book Club"
        assert result.slug
        assert len(result.members) == 1
        assert result.members[0].user_id == SOME_USER_ID
        club_repo.save.assert_awaited_once()


def describe_admit_user():
    async def it_raises_when_the_club_does_not_exist(club_repo: AsyncMock):
        club_repo.find_by_id.return_value = None
        service = ClubService(club_repo)

        with pytest.raises(ClubNotFoundError):
            await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

    async def it_short_circuits_when_the_user_is_already_a_member(club_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club()
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        service = ClubService(club_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.ALREADY_MEMBER
        club_repo.add_member.assert_not_called()
        club_repo.add_to_pending_approvals.assert_not_called()

    async def it_admits_directly_when_the_join_policy_is_public(club_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.PUBLIC)
        club_repo.exists_by_club_id_and_member_user_id.return_value = False
        service = ClubService(club_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.JOINED
        club_repo.add_member.assert_awaited_once()
        club_repo.add_to_pending_approvals.assert_not_called()

    async def it_admits_directly_for_a_direct_invite_regardless_of_join_policy(club_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.RESTRICTED)
        club_repo.exists_by_club_id_and_member_user_id.return_value = False
        service = ClubService(club_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID, is_direct=True)

        assert result.status == ClubOnboardingStatus.JOINED
        club_repo.add_member.assert_awaited_once()

    async def it_queues_for_approval_when_the_join_policy_is_restricted(club_repo: AsyncMock):
        club_repo.find_by_id.return_value = _club(join_policy=JoinPolicy.RESTRICTED)
        club_repo.exists_by_club_id_and_member_user_id.return_value = False
        service = ClubService(club_repo)

        result = await service.admit_user(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result.status == ClubOnboardingStatus.PENDING_APPROVAL
        club_repo.add_to_pending_approvals.assert_awaited_once_with(SOME_CLUB_ID, SOME_USER_ID)
        club_repo.add_member.assert_not_called()


def describe_get_preferred_languages():
    async def it_returns_the_clubs_preferred_languages_for_a_member(club_repo: AsyncMock):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.get_preferred_languages_by_id.return_value = ["en", "pt-BR"]
        service = ClubService(club_repo)

        result = await service.get_preferred_languages(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        assert result == ["en", "pt-BR"]

    async def it_raises_when_the_user_is_not_a_member(club_repo: AsyncMock):
        club_repo.exists_by_club_id_and_member_user_id.return_value = False
        service = ClubService(club_repo)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.get_preferred_languages(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)

        club_repo.get_preferred_languages_by_id.assert_not_called()

    async def it_propagates_a_club_not_found_error_from_the_repository(club_repo: AsyncMock):
        club_repo.exists_by_club_id_and_member_user_id.return_value = True
        club_repo.get_preferred_languages_by_id.side_effect = ClubNotFoundError("not found")
        service = ClubService(club_repo)

        with pytest.raises(ClubNotFoundError):
            await service.get_preferred_languages(club_id=SOME_CLUB_ID, user_id=SOME_USER_ID)
