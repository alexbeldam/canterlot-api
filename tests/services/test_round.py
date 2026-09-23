import random
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId
from dateutil.relativedelta import relativedelta

from canterlot.dto.round import DeadlineRequest, StartRoundRequest
from canterlot.exceptions import (
    ActiveRoundAlreadyExistsError,
    NoEligibleCatalogError,
    RoundAlreadyFinalizedError,
    RoundNotFoundError,
    UnauthorizedClubMemberError,
)
from canterlot.models.round import CandidatePoolEntry, DeadlineDuration
from canterlot.repositories import CompletionResult
from canterlot.services.round import RoundService
from canterlot.types import (
    DeadlineType,
    DeadlineUnit,
    MemberRole,
    RoundResolutionMethod,
    RoundSelectionMode,
    RoundStatus,
)
from tools.factories import BookFactory, CatalogEntryFactory, ClubFactory, RoundFactory

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")
OWNER_ID = PydanticObjectId("507f1f77bcf86cd799439012")
MEMBER_ID = PydanticObjectId("507f1f77bcf86cd799439013")
NOW = datetime(2026, 1, 15, tzinfo=UTC)


def _service(
    round_repo: AsyncMock,
    book_repo: AsyncMock,
    read_book_repo: AsyncMock,
    round_completion_repo: AsyncMock,
    club_membership_repo: AsyncMock,
    user_repo: AsyncMock,
    catalog_repo: AsyncMock,
) -> RoundService:
    round_repo.save.side_effect = lambda round_: round_
    book_repo.find_by_ids.return_value = {}
    read_book_repo.find_rating_stats_by_book_ids.return_value = {}
    read_book_repo.count_readers_among_users.return_value = {}
    round_completion_repo.find_majority_excluded_book_ids.return_value = set()
    club_membership_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.OWNER
    club_membership_repo.find_active_member_ids_by_club_id.return_value = [OWNER_ID]
    club_membership_repo.exists_by_club_id_and_member_user_id.return_value = True
    catalog_repo.find_by_club_id_excluding_book_ids.return_value = []
    catalog_repo.find_by_club_id_and_book_ids.return_value = []
    return RoundService(
        round_repo,
        book_repo,
        read_book_repo,
        round_completion_repo,
        club_membership_repo,
        user_repo,
        catalog_repo,
        rng=random.Random(1),
    )


def _club():
    return ClubFactory.build(id=SOME_CLUB_ID, preferred_languages=[])


def _catalog_entry(book_id, suggested_by, days_ago=1):
    return CatalogEntryFactory.build(
        club_id=SOME_CLUB_ID,
        book_id=book_id,
        suggested_by=suggested_by,
        suggested_at=NOW - timedelta(days=days_ago),
    )


def describe_start_round():
    async def it_rejects_a_caller_below_admin_rank(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        club_membership_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.MEMBER
        club = _club()
        payload = StartRoundRequest(selection_mode=RoundSelectionMode.RANDOM)

        with pytest.raises(UnauthorizedClubMemberError):
            await service.start_round(club, MEMBER_ID, payload, NOW)

    async def it_rejects_when_an_active_round_already_exists(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = RoundFactory.build(status=RoundStatus.SETUP)
        club = _club()
        payload = StartRoundRequest(selection_mode=RoundSelectionMode.RANDOM)

        with pytest.raises(ActiveRoundAlreadyExistsError):
            await service.start_round(club, OWNER_ID, payload, NOW)

    async def it_rejects_when_the_eligible_catalog_is_empty(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None
        catalog_repo.find_by_club_id_excluding_book_ids.return_value = []
        club = _club()
        payload = StartRoundRequest(selection_mode=RoundSelectionMode.CURATED)

        with pytest.raises(NoEligibleCatalogError):
            await service.start_round(club, OWNER_ID, payload, NOW)

    async def it_rejects_when_every_catalog_book_is_already_completed(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None
        book_id = PydanticObjectId()
        catalog_repo.find_by_club_id_excluding_book_ids.return_value = []
        club = _club()
        round_completion_repo.find_majority_excluded_book_ids.return_value = {book_id}
        payload = StartRoundRequest(selection_mode=RoundSelectionMode.RANDOM)

        with pytest.raises(NoEligibleCatalogError):
            await service.start_round(club, OWNER_ID, payload, NOW)

        catalog_repo.find_by_club_id_excluding_book_ids.assert_awaited_once_with(SOME_CLUB_ID, {book_id})

    async def it_locks_in_the_single_eligible_book_regardless_of_selection_mode(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None
        book_id = PydanticObjectId()
        catalog_repo.find_by_club_id_excluding_book_ids.return_value = [_catalog_entry(book_id, OWNER_ID)]
        club = _club()
        payload = StartRoundRequest(selection_mode=RoundSelectionMode.CURATED)

        result = await service.start_round(club, OWNER_ID, payload, NOW)

        assert result.status == RoundStatus.DECIDED
        assert result.book_id == book_id
        assert result.candidate_pool == []
        assert result.decided_at == NOW
        book_repo.find_by_ids.assert_not_called()

    async def it_creates_a_fully_decided_round_in_random_mode(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None
        book_a, book_b = PydanticObjectId(), PydanticObjectId()
        book_repo.find_by_ids.return_value = {
            book_a: BookFactory.build(languages=[]),
            book_b: BookFactory.build(languages=[]),
        }
        catalog_repo.find_by_club_id_excluding_book_ids.return_value = [
            _catalog_entry(book_a, OWNER_ID),
            _catalog_entry(book_b, MEMBER_ID),
        ]
        club = _club()
        payload = StartRoundRequest(selection_mode=RoundSelectionMode.RANDOM)

        result = await service.start_round(club, OWNER_ID, payload, NOW)

        assert result.status == RoundStatus.DECIDED
        assert result.book_id in {book_a, book_b}
        assert result.decided_at == NOW
        assert result.candidate_pool == []
        club_membership_repo.find_active_member_ids_by_club_id.assert_awaited_once()

    async def it_creates_a_setup_phase_round_with_an_auto_generated_pool_in_curated_mode(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None
        book_a, book_b = PydanticObjectId(), PydanticObjectId()
        book_repo.find_by_ids.return_value = {
            book_a: BookFactory.build(languages=[]),
            book_b: BookFactory.build(languages=[]),
        }
        catalog_repo.find_by_club_id_excluding_book_ids.return_value = [
            _catalog_entry(book_a, OWNER_ID),
            _catalog_entry(book_b, MEMBER_ID),
        ]
        club = _club()
        payload = StartRoundRequest(selection_mode=RoundSelectionMode.CURATED)

        result = await service.start_round(club, OWNER_ID, payload, NOW)

        assert result.status == RoundStatus.SETUP
        assert result.book_id is None
        assert {entry.book_id for entry in result.candidate_pool} == {book_a, book_b}

    async def it_resolves_a_preset_deadline_immediately_when_the_book_is_decided_at_creation(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None
        book_id = PydanticObjectId()
        catalog_repo.find_by_club_id_excluding_book_ids.return_value = [_catalog_entry(book_id, OWNER_ID)]
        club = _club()
        payload = StartRoundRequest(
            selection_mode=RoundSelectionMode.RANDOM,
            deadline=DeadlineRequest(type=DeadlineType.PRESET, value=2, unit=DeadlineUnit.WEEKS),
        )

        result = await service.start_round(club, OWNER_ID, payload, NOW)

        assert result.deadline_duration is None
        assert result.deadline == NOW + timedelta(weeks=2)

    async def it_resolves_a_months_preset_deadline_immediately_when_the_book_is_decided_at_creation(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None
        book_id = PydanticObjectId()
        catalog_repo.find_by_club_id_excluding_book_ids.return_value = [_catalog_entry(book_id, OWNER_ID)]
        club = _club()
        payload = StartRoundRequest(
            selection_mode=RoundSelectionMode.RANDOM,
            deadline=DeadlineRequest(type=DeadlineType.PRESET, value=1, unit=DeadlineUnit.MONTHS),
        )

        result = await service.start_round(club, OWNER_ID, payload, NOW)

        assert result.deadline_duration is None
        assert result.deadline == NOW + relativedelta(months=1)

    async def it_stores_a_custom_target_date_deadline_immediately_regardless_of_mode(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None
        book_a, book_b = PydanticObjectId(), PydanticObjectId()
        book_repo.find_by_ids.return_value = {
            book_a: BookFactory.build(languages=[]),
            book_b: BookFactory.build(languages=[]),
        }
        catalog_repo.find_by_club_id_excluding_book_ids.return_value = [
            _catalog_entry(book_a, OWNER_ID),
            _catalog_entry(book_b, MEMBER_ID),
        ]
        club = _club()
        payload = StartRoundRequest(
            selection_mode=RoundSelectionMode.CURATED,
            deadline=DeadlineRequest(type=DeadlineType.CUSTOM, target_date=date(2026, 6, 1)),
        )

        result = await service.start_round(club, OWNER_ID, payload, NOW)

        assert result.status == RoundStatus.SETUP
        assert result.deadline_duration is None
        assert result.deadline == datetime(2026, 6, 1, tzinfo=UTC)

    async def it_leaves_the_preset_unresolved_for_a_curated_round_in_setup(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None
        book_a, book_b = PydanticObjectId(), PydanticObjectId()
        book_repo.find_by_ids.return_value = {
            book_a: BookFactory.build(languages=[]),
            book_b: BookFactory.build(languages=[]),
        }
        catalog_repo.find_by_club_id_excluding_book_ids.return_value = [
            _catalog_entry(book_a, OWNER_ID),
            _catalog_entry(book_b, MEMBER_ID),
        ]
        club = _club()
        payload = StartRoundRequest(
            selection_mode=RoundSelectionMode.CURATED,
            deadline=DeadlineRequest(type=DeadlineType.PRESET, value=1, unit=DeadlineUnit.MONTHS),
        )

        result = await service.start_round(club, OWNER_ID, payload, NOW)

        assert result.deadline is None
        assert result.deadline_duration is not None
        assert result.deadline_duration.value == 1
        assert result.deadline_duration.unit == DeadlineUnit.MONTHS


def describe_finalize_round():
    def _active_round(**overrides):
        defaults = {
            "id": PydanticObjectId(),
            "club_id": SOME_CLUB_ID,
            "started_by": OWNER_ID,
            "selection_mode": RoundSelectionMode.CURATED,
            "status": RoundStatus.SETUP,
        }
        defaults.update(overrides)
        return RoundFactory.build(**defaults)

    async def it_rejects_a_caller_below_admin_rank(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        club_membership_repo.find_member_role_by_club_id_and_user_id.return_value = MemberRole.MEMBER
        club = _club()

        with pytest.raises(UnauthorizedClubMemberError):
            await service.finalize_round(club, MEMBER_ID, RoundResolutionMethod.DRAW, NOW)

    async def it_rejects_when_no_active_round_exists(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None
        club = _club()

        with pytest.raises(RoundNotFoundError):
            await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.DRAW, NOW)

    async def it_rejects_when_the_round_is_not_in_setup(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = _active_round(status=RoundStatus.VOTING)
        club = _club()

        with pytest.raises(RoundAlreadyFinalizedError):
            await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.DRAW, NOW)

    async def it_finalizes_via_draw_and_locks_in_a_book(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_a, book_b = PydanticObjectId(), PydanticObjectId()
        book_repo.find_by_ids.return_value = {
            book_a: BookFactory.build(languages=[]),
            book_b: BookFactory.build(languages=[]),
        }
        round_ = _active_round(candidate_pool=[CandidatePoolEntry(book_id=book_a), CandidatePoolEntry(book_id=book_b)])
        round_repo.find_active_by_club_id.return_value = round_
        round_repo.finalize_with_draw.return_value = True
        catalog_repo.find_by_club_id_and_book_ids.return_value = [
            _catalog_entry(book_a, OWNER_ID),
            _catalog_entry(book_b, MEMBER_ID),
        ]
        club = _club()

        result = await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.DRAW, NOW)

        assert result.status == RoundStatus.DECIDED
        assert result.resolution_method == RoundResolutionMethod.DRAW
        assert result.book_id in {book_a, book_b}
        assert result.decided_at == NOW
        round_repo.finalize_with_draw.assert_awaited_once()
        catalog_repo.find_by_club_id_and_book_ids.assert_awaited_once_with(SOME_CLUB_ID, {book_a, book_b})

    async def it_finalizes_via_vote_and_opens_voting_without_a_book(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_ = _active_round()
        round_repo.find_active_by_club_id.return_value = round_
        round_repo.finalize_with_vote.return_value = True
        club = _club()

        result = await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.VOTE, NOW)

        assert result.status == RoundStatus.VOTING
        assert result.resolution_method == RoundResolutionMethod.VOTE
        assert result.book_id is None
        round_repo.finalize_with_vote.assert_awaited_once()

    async def it_rejects_finalizing_an_already_finalized_round_on_a_racing_draw(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_id = PydanticObjectId()
        book_repo.find_by_ids.return_value = {book_id: BookFactory.build(languages=[])}
        round_ = _active_round(candidate_pool=[CandidatePoolEntry(book_id=book_id)])
        round_repo.find_active_by_club_id.return_value = round_
        round_repo.finalize_with_draw.return_value = False
        catalog_repo.find_by_club_id_and_book_ids.return_value = [_catalog_entry(book_id, OWNER_ID)]
        club = _club()

        with pytest.raises(RoundAlreadyFinalizedError):
            await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.DRAW, NOW)

    async def it_resolves_the_preset_deadline_at_finalize_time_for_a_draw(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_id = PydanticObjectId()
        book_repo.find_by_ids.return_value = {book_id: BookFactory.build(languages=[])}
        round_ = _active_round(
            candidate_pool=[CandidatePoolEntry(book_id=book_id)],
            deadline_duration=DeadlineDuration(value=1, unit=DeadlineUnit.MONTHS),
        )
        round_repo.find_active_by_club_id.return_value = round_
        round_repo.finalize_with_draw.return_value = True
        catalog_repo.find_by_club_id_and_book_ids.return_value = [_catalog_entry(book_id, OWNER_ID)]
        club = _club()

        result = await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.DRAW, NOW)

        assert result.deadline == NOW + relativedelta(months=1)
        round_repo.finalize_with_draw.assert_awaited_once_with(round_.id, book_id, NOW, NOW + relativedelta(months=1))

    async def it_resolves_a_months_preset_deadline_across_a_month_end_at_finalize_time(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_id = PydanticObjectId()
        book_repo.find_by_ids.return_value = {book_id: BookFactory.build(languages=[])}
        started_at = datetime(2026, 1, 31, tzinfo=UTC)
        round_ = _active_round(
            candidate_pool=[CandidatePoolEntry(book_id=book_id)],
            deadline_duration=DeadlineDuration(value=1, unit=DeadlineUnit.MONTHS),
        )
        round_repo.find_active_by_club_id.return_value = round_
        round_repo.finalize_with_draw.return_value = True
        catalog_repo.find_by_club_id_and_book_ids.return_value = [_catalog_entry(book_id, OWNER_ID)]
        club = _club()

        result = await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.DRAW, started_at)

        assert result.deadline == datetime(2026, 2, 28, tzinfo=UTC)

    async def it_resolves_a_multi_month_preset_deadline_without_compounding_drift(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_id = PydanticObjectId()
        book_repo.find_by_ids.return_value = {book_id: BookFactory.build(languages=[])}
        started_at = datetime(2026, 1, 31, tzinfo=UTC)
        round_ = _active_round(
            candidate_pool=[CandidatePoolEntry(book_id=book_id)],
            deadline_duration=DeadlineDuration(value=3, unit=DeadlineUnit.MONTHS),
        )
        round_repo.find_active_by_club_id.return_value = round_
        round_repo.finalize_with_draw.return_value = True
        catalog_repo.find_by_club_id_and_book_ids.return_value = [_catalog_entry(book_id, OWNER_ID)]
        club = _club()

        result = await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.DRAW, started_at)

        assert result.deadline == datetime(2026, 4, 30, tzinfo=UTC)

    async def it_resolves_a_days_preset_at_finalize_time(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_id = PydanticObjectId()
        book_repo.find_by_ids.return_value = {book_id: BookFactory.build(languages=[])}
        round_ = _active_round(
            candidate_pool=[CandidatePoolEntry(book_id=book_id)],
            deadline_duration=DeadlineDuration(value=3, unit=DeadlineUnit.DAYS),
        )
        round_repo.find_active_by_club_id.return_value = round_
        round_repo.finalize_with_draw.return_value = True
        catalog_repo.find_by_club_id_and_book_ids.return_value = [_catalog_entry(book_id, OWNER_ID)]
        club = _club()

        result = await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.DRAW, NOW)

        assert result.deadline == NOW + timedelta(days=3)

    async def it_rejects_finalizing_via_vote_when_the_round_state_changed_first(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = _active_round()
        round_repo.finalize_with_vote.return_value = False
        club = _club()

        with pytest.raises(RoundAlreadyFinalizedError):
            await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.VOTE, NOW)

    async def it_never_resolves_a_deadline_when_opening_for_a_vote(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_ = _active_round(deadline_duration=DeadlineDuration(value=2, unit=DeadlineUnit.WEEKS))
        round_repo.find_active_by_club_id.return_value = round_
        round_repo.finalize_with_vote.return_value = True
        club = _club()

        result = await service.finalize_round(club, OWNER_ID, RoundResolutionMethod.VOTE, NOW)

        assert result.deadline is None
        round_repo.finalize_with_vote.assert_awaited_once_with(round_.id)


def describe_resolve_display():
    async def it_returns_nothing_when_the_round_has_no_book_or_pool(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_ = RoundFactory.build(book_id=None, candidate_pool=[])

        display = await service.resolve_display(round_)

        assert display.book is None
        assert display.pool_books == []
        assert display.rating_stats == {}
        book_repo.find_by_ids.assert_not_called()

    async def it_resolves_the_decided_book(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_id = PydanticObjectId()
        book = BookFactory.build(id=book_id)
        book_repo.find_by_ids.return_value = {book_id: book}
        round_ = RoundFactory.build(book_id=book_id, candidate_pool=[])

        display = await service.resolve_display(round_)

        assert display.book == book
        assert display.pool_books == []

    async def it_resolves_the_candidate_pool_books(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_a, book_b = PydanticObjectId(), PydanticObjectId()
        books = {book_a: BookFactory.build(id=book_a), book_b: BookFactory.build(id=book_b)}
        book_repo.find_by_ids.return_value = books
        round_ = RoundFactory.build(
            book_id=None,
            candidate_pool=[CandidatePoolEntry(book_id=book_a), CandidatePoolEntry(book_id=book_b)],
        )

        display = await service.resolve_display(round_)

        assert display.book is None
        assert {book.id for book in display.pool_books} == {book_a, book_b}


def describe_get_progress():
    async def it_lists_every_current_member_with_their_finished_state(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_id = PydanticObjectId()
        round_id = PydanticObjectId()
        finished_member, unfinished_member = PydanticObjectId(), PydanticObjectId()
        round_repo.find_active_by_club_id.return_value = RoundFactory.build(
            id=round_id,
            club_id=SOME_CLUB_ID,
            status=RoundStatus.DECIDED,
            book_id=book_id,
            candidate_pool=[],
        )
        club_membership_repo.find_active_member_ids_by_club_id.return_value = [finished_member, unfinished_member]
        round_completion_repo.find_user_ids_by_round_id.return_value = {finished_member}
        user_repo.get_usernames_by_ids.return_value = {finished_member: "alice", unfinished_member: "bob"}

        progress = await service.get_progress(SOME_CLUB_ID, finished_member)

        assert {(entry.username, entry.finished) for entry in progress} == {("alice", True), ("bob", False)}

    async def it_raises_round_not_found_when_no_decided_round_exists(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None

        with pytest.raises(RoundNotFoundError):
            await service.get_progress(SOME_CLUB_ID, MEMBER_ID)

    async def it_raises_round_not_found_when_the_round_is_still_in_setup_or_voting(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = RoundFactory.build(
            club_id=SOME_CLUB_ID,
            status=RoundStatus.SETUP,
            book_id=None,
            candidate_pool=[],
        )

        with pytest.raises(RoundNotFoundError):
            await service.get_progress(SOME_CLUB_ID, MEMBER_ID)

    async def it_raises_unauthorized_when_caller_is_not_a_member(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        club_membership_repo.exists_by_club_id_and_member_user_id.return_value = False

        with pytest.raises(UnauthorizedClubMemberError):
            await service.get_progress(SOME_CLUB_ID, MEMBER_ID)


def describe_mark_finished():
    async def it_records_a_completion_and_upserts_the_read_book_history(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_id = PydanticObjectId()
        round_id = PydanticObjectId()
        club_membership_repo.find_active_member_ids_by_club_id.return_value = [MEMBER_ID]
        round_repo.find_active_by_club_id.return_value = RoundFactory.build(
            id=round_id,
            club_id=SOME_CLUB_ID,
            status=RoundStatus.DECIDED,
            book_id=book_id,
            candidate_pool=[],
        )
        round_completion_repo.record_completion.return_value = CompletionResult(is_new=True, round_concluded=False)

        await service.mark_finished(SOME_CLUB_ID, MEMBER_ID, 4.5, NOW)

        round_completion_repo.record_completion.assert_awaited_once_with(
            SOME_CLUB_ID,
            round_id,
            book_id,
            MEMBER_ID,
            NOW,
            {MEMBER_ID},
        )
        read_book_repo.upsert.assert_awaited_once_with(MEMBER_ID, book_id, 4.5)

    async def it_still_updates_the_rating_on_a_replayed_call(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_id = PydanticObjectId()
        club_membership_repo.find_active_member_ids_by_club_id.return_value = [MEMBER_ID]
        round_repo.find_active_by_club_id.return_value = RoundFactory.build(
            club_id=SOME_CLUB_ID,
            status=RoundStatus.DECIDED,
            book_id=book_id,
            candidate_pool=[],
        )
        round_completion_repo.record_completion.return_value = CompletionResult(is_new=False, round_concluded=False)

        await service.mark_finished(SOME_CLUB_ID, MEMBER_ID, 3.0, NOW)

        read_book_repo.upsert.assert_awaited_once_with(MEMBER_ID, book_id, 3.0)

    async def it_still_upserts_the_read_book_history_when_the_round_auto_closes(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        book_id = PydanticObjectId()
        club_membership_repo.find_active_member_ids_by_club_id.return_value = [MEMBER_ID]
        round_repo.find_active_by_club_id.return_value = RoundFactory.build(
            club_id=SOME_CLUB_ID,
            status=RoundStatus.DECIDED,
            book_id=book_id,
            candidate_pool=[],
        )
        round_completion_repo.record_completion.return_value = CompletionResult(is_new=True, round_concluded=True)

        await service.mark_finished(SOME_CLUB_ID, MEMBER_ID, None, NOW)

        read_book_repo.upsert.assert_awaited_once_with(MEMBER_ID, book_id, None)

    async def it_raises_round_not_found_when_no_decided_round_exists(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        round_repo.find_active_by_club_id.return_value = None

        with pytest.raises(RoundNotFoundError):
            await service.mark_finished(SOME_CLUB_ID, MEMBER_ID, None, NOW)

    async def it_raises_unauthorized_when_caller_is_not_a_member(
        round_repo: AsyncMock,
        book_repo: AsyncMock,
        read_book_repo: AsyncMock,
        round_completion_repo: AsyncMock,
        club_membership_repo: AsyncMock,
        user_repo: AsyncMock,
        catalog_repo: AsyncMock,
    ):
        service = _service(
            round_repo,
            book_repo,
            read_book_repo,
            round_completion_repo,
            club_membership_repo,
            user_repo,
            catalog_repo,
        )
        club_membership_repo.exists_by_club_id_and_member_user_id.return_value = False

        with pytest.raises(UnauthorizedClubMemberError):
            await service.mark_finished(SOME_CLUB_ID, MEMBER_ID, None, NOW)
