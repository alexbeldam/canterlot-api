from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId

from canterlot.hoodie import link_id
from canterlot.models import ClubModel, UserModel
from canterlot.repositories.beanie.round import BeanieRoundRepository
from canterlot.types import RoundResolutionMethod, RoundSelectionMode, RoundStatus
from tools.factories import RoundFactory

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieRoundRepository()


def _id(document) -> PydanticObjectId:
    return PydanticObjectId(document.id)


def describe_find_active_by_club_id():
    async def it_returns_none_when_no_round_exists_for_the_club():
        found = await repo.find_active_by_club_id(PydanticObjectId())

        assert found is None

    @pytest.mark.parametrize("status", [RoundStatus.SETUP, RoundStatus.VOTING, RoundStatus.DECIDED])
    async def it_finds_an_active_round_regardless_of_which_active_status(status: RoundStatus):
        club_id = PydanticObjectId()
        round_ = await RoundFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            started_by=UserModel.link_from_id(PydanticObjectId()),
            selection_mode=RoundSelectionMode.CURATED,
            status=status,
        )

        found = await repo.find_active_by_club_id(club_id)

        assert found is not None
        assert _id(found) == _id(round_)

    @pytest.mark.parametrize("status", [RoundStatus.CONCLUDED, RoundStatus.CANCELLED])
    async def it_ignores_terminal_rounds(status: RoundStatus):
        club_id = PydanticObjectId()
        await RoundFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            started_by=UserModel.link_from_id(PydanticObjectId()),
            selection_mode=RoundSelectionMode.RANDOM,
            status=status,
        )

        found = await repo.find_active_by_club_id(club_id)

        assert found is None


def describe_finalize_with_draw():
    async def it_locks_in_the_book_when_the_round_is_still_in_setup():
        round_ = await RoundFactory.create_async(
            club=ClubModel.link_from_id(PydanticObjectId()),
            started_by=UserModel.link_from_id(PydanticObjectId()),
            selection_mode=RoundSelectionMode.CURATED,
            status=RoundStatus.SETUP,
        )
        book_id = PydanticObjectId()
        decided_at = datetime.now(UTC)
        deadline = decided_at + timedelta(days=14)

        changed = await repo.finalize_with_draw(_id(round_), book_id, decided_at, deadline)

        assert changed is True
        refreshed = await repo.find_active_by_club_id(link_id(round_.club))
        assert refreshed is not None
        assert refreshed.status == RoundStatus.DECIDED
        assert refreshed.resolution_method == RoundResolutionMethod.DRAW
        assert link_id(refreshed.book) == book_id
        assert refreshed.deadline is not None
        assert abs((refreshed.deadline - deadline).total_seconds()) < 1

    async def it_does_nothing_when_the_round_is_no_longer_in_setup():
        round_ = await RoundFactory.create_async(
            club=ClubModel.link_from_id(PydanticObjectId()),
            started_by=UserModel.link_from_id(PydanticObjectId()),
            selection_mode=RoundSelectionMode.CURATED,
            status=RoundStatus.VOTING,
        )

        changed = await repo.finalize_with_draw(_id(round_), PydanticObjectId(), datetime.now(UTC), None)

        assert changed is False

    async def it_leaves_an_existing_deadline_untouched_when_no_new_deadline_is_given():
        preset_deadline = datetime.now(UTC) + timedelta(days=30)
        round_ = await RoundFactory.create_async(
            club=ClubModel.link_from_id(PydanticObjectId()),
            started_by=UserModel.link_from_id(PydanticObjectId()),
            selection_mode=RoundSelectionMode.CURATED,
            status=RoundStatus.SETUP,
            deadline=preset_deadline,
        )

        changed = await repo.finalize_with_draw(_id(round_), PydanticObjectId(), datetime.now(UTC), None)

        assert changed is True
        refreshed = await repo.find_active_by_club_id(link_id(round_.club))
        assert refreshed is not None
        assert refreshed.deadline is not None
        assert abs((refreshed.deadline - preset_deadline).total_seconds()) < 1


def describe_finalize_with_vote():
    async def it_opens_voting_when_the_round_is_still_in_setup():
        round_ = await RoundFactory.create_async(
            club=ClubModel.link_from_id(PydanticObjectId()),
            started_by=UserModel.link_from_id(PydanticObjectId()),
            selection_mode=RoundSelectionMode.CURATED,
            status=RoundStatus.SETUP,
        )

        changed = await repo.finalize_with_vote(_id(round_))

        assert changed is True
        refreshed = await repo.find_active_by_club_id(link_id(round_.club))
        assert refreshed is not None
        assert refreshed.status == RoundStatus.VOTING
        assert refreshed.resolution_method == RoundResolutionMethod.VOTE
        assert link_id(refreshed.book) is None

    async def it_does_nothing_when_the_round_is_no_longer_in_setup():
        round_ = await RoundFactory.create_async(
            club=ClubModel.link_from_id(PydanticObjectId()),
            started_by=UserModel.link_from_id(PydanticObjectId()),
            selection_mode=RoundSelectionMode.CURATED,
            status=RoundStatus.DECIDED,
        )

        changed = await repo.finalize_with_vote(_id(round_))

        assert changed is False


def describe_save():
    async def it_inserts_a_new_round():
        round_ = RoundFactory.build(
            club=ClubModel.link_from_id(PydanticObjectId()),
            started_by=UserModel.link_from_id(PydanticObjectId()),
            selection_mode=RoundSelectionMode.RANDOM,
            status=RoundStatus.DECIDED,
        )

        saved = await repo.save(round_)

        assert saved.id is not None
        found = await repo.find_active_by_club_id(link_id(round_.club))
        assert found is not None
