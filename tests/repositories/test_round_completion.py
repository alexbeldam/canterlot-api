from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId

from canterlot.models import BookModel, ClubModel, UserModel
from canterlot.models.round import RoundModel
from canterlot.repositories.beanie.round_completion import BeanieRoundCompletionRepository
from canterlot.types import RoundSelectionMode, RoundStatus
from tools.factories import RoundCompletionFactory, RoundFactory

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieRoundCompletionRepository()


async def _decided_round(club_id: PydanticObjectId, book_id: PydanticObjectId) -> RoundModel:
    return await RoundFactory.create_async(
        club=ClubModel.link_from_id(club_id),
        started_by=UserModel.link_from_id(PydanticObjectId()),
        selection_mode=RoundSelectionMode.RANDOM,
        status=RoundStatus.DECIDED,
        book=BookModel.link_from_id(book_id),
        candidate_pool=[],
    )


def _id(document) -> PydanticObjectId:
    return PydanticObjectId(document.id)


def describe_find_majority_excluded_book_ids():
    async def it_excludes_a_book_when_a_majority_of_a_rounds_finishers_are_still_current_members():
        club_id = PydanticObjectId()
        round_id = PydanticObjectId()
        book_id = PydanticObjectId()
        finisher_a, finisher_b, finisher_c = PydanticObjectId(), PydanticObjectId(), PydanticObjectId()
        for user_id in (finisher_a, finisher_b, finisher_c):
            await RoundCompletionFactory.create_async(
                club=ClubModel.link_from_id(club_id),
                round=RoundModel.link_from_id(round_id),
                book=BookModel.link_from_id(book_id),
                user=UserModel.link_from_id(user_id),
            )

        excluded = await repo.find_majority_excluded_book_ids(club_id, {finisher_a, finisher_b})

        assert excluded == {book_id}

    async def it_does_not_exclude_a_book_when_finishers_have_dropped_to_a_minority():
        club_id = PydanticObjectId()
        round_id = PydanticObjectId()
        book_id = PydanticObjectId()
        finisher_a, finisher_b, finisher_c = PydanticObjectId(), PydanticObjectId(), PydanticObjectId()
        for user_id in (finisher_a, finisher_b, finisher_c):
            await RoundCompletionFactory.create_async(
                club=ClubModel.link_from_id(club_id),
                round=RoundModel.link_from_id(round_id),
                book=BookModel.link_from_id(book_id),
                user=UserModel.link_from_id(user_id),
            )

        excluded = await repo.find_majority_excluded_book_ids(club_id, {finisher_a})

        assert excluded == set()

    async def it_does_not_exclude_when_exactly_half_of_finishers_remain():
        club_id = PydanticObjectId()
        round_id = PydanticObjectId()
        book_id = PydanticObjectId()
        finisher_a, finisher_b = PydanticObjectId(), PydanticObjectId()
        for user_id in (finisher_a, finisher_b):
            await RoundCompletionFactory.create_async(
                club=ClubModel.link_from_id(club_id),
                round=RoundModel.link_from_id(round_id),
                book=BookModel.link_from_id(book_id),
                user=UserModel.link_from_id(user_id),
            )

        excluded = await repo.find_majority_excluded_book_ids(club_id, {finisher_a})

        assert excluded == set()

    async def it_evaluates_each_round_completion_independently_for_the_same_book():
        club_id = PydanticObjectId()
        book_id = PydanticObjectId()
        majority_round_id = PydanticObjectId()
        minority_round_id = PydanticObjectId()
        majority_finisher_a, majority_finisher_b = PydanticObjectId(), PydanticObjectId()
        minority_finisher_a, minority_finisher_b, minority_finisher_c = (
            PydanticObjectId(),
            PydanticObjectId(),
            PydanticObjectId(),
        )
        for user_id in (majority_finisher_a, majority_finisher_b):
            await RoundCompletionFactory.create_async(
                club=ClubModel.link_from_id(club_id),
                round=RoundModel.link_from_id(majority_round_id),
                book=BookModel.link_from_id(book_id),
                user=UserModel.link_from_id(user_id),
            )
        for user_id in (minority_finisher_a, minority_finisher_b, minority_finisher_c):
            await RoundCompletionFactory.create_async(
                club=ClubModel.link_from_id(club_id),
                round=RoundModel.link_from_id(minority_round_id),
                book=BookModel.link_from_id(book_id),
                user=UserModel.link_from_id(user_id),
            )

        excluded = await repo.find_majority_excluded_book_ids(
            club_id,
            {majority_finisher_a, majority_finisher_b, minority_finisher_a},
        )

        assert excluded == {book_id}

    async def it_returns_an_empty_set_when_the_club_has_no_completions():
        club_id = PydanticObjectId()

        excluded = await repo.find_majority_excluded_book_ids(club_id, {PydanticObjectId()})

        assert excluded == set()


def describe_find_user_ids_by_round_id():
    async def it_returns_the_set_of_user_ids_who_completed_a_round():
        round_id = PydanticObjectId()
        finisher_a, finisher_b = PydanticObjectId(), PydanticObjectId()
        for user_id in (finisher_a, finisher_b):
            await RoundCompletionFactory.create_async(
                club=ClubModel.link_from_id(PydanticObjectId()),
                round=RoundModel.link_from_id(round_id),
                book=BookModel.link_from_id(PydanticObjectId()),
                user=UserModel.link_from_id(user_id),
            )

        finishers = await repo.find_user_ids_by_round_id(round_id)

        assert finishers == {finisher_a, finisher_b}

    async def it_returns_an_empty_set_when_nobody_has_finished():
        finishers = await repo.find_user_ids_by_round_id(PydanticObjectId())

        assert finishers == set()


def describe_record_completion():
    async def it_records_a_new_completion_and_does_not_conclude_when_members_remain():
        club_id = PydanticObjectId()
        book_id = PydanticObjectId()
        finisher, still_reading = PydanticObjectId(), PydanticObjectId()
        round_ = await _decided_round(club_id, book_id)
        round_id = PydanticObjectId(round_.id)

        result = await repo.record_completion(
            club_id,
            round_id,
            book_id,
            finisher,
            datetime.now(UTC),
            {finisher, still_reading},
        )

        assert result.is_new is True
        assert result.round_concluded is False
        assert await repo.find_user_ids_by_round_id(round_id) == {finisher}
        refreshed = await RoundModel.get(round_id)
        assert refreshed is not None
        assert refreshed.status == RoundStatus.DECIDED

    async def it_concludes_the_round_when_the_last_current_member_finishes():
        club_id = PydanticObjectId()
        book_id = PydanticObjectId()
        first_finisher, last_finisher = PydanticObjectId(), PydanticObjectId()
        round_ = await _decided_round(club_id, book_id)
        round_id = PydanticObjectId(round_.id)
        current_member_ids = {first_finisher, last_finisher}
        await repo.record_completion(club_id, round_id, book_id, first_finisher, datetime.now(UTC), current_member_ids)

        result = await repo.record_completion(
            club_id,
            round_id,
            book_id,
            last_finisher,
            datetime.now(UTC),
            current_member_ids,
        )

        assert result.is_new is True
        assert result.round_concluded is True
        refreshed = await RoundModel.get(round_id)
        assert refreshed is not None
        assert refreshed.status == RoundStatus.CONCLUDED

    async def it_ignores_members_who_left_when_evaluating_auto_close():
        club_id = PydanticObjectId()
        book_id = PydanticObjectId()
        remaining_member = PydanticObjectId()
        former_member = PydanticObjectId()
        round_ = await _decided_round(club_id, book_id)
        round_id = PydanticObjectId(round_.id)
        await RoundCompletionFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            round=RoundModel.link_from_id(round_id),
            book=BookModel.link_from_id(book_id),
            user=UserModel.link_from_id(former_member),
        )

        result = await repo.record_completion(
            club_id,
            round_id,
            book_id,
            remaining_member,
            datetime.now(UTC),
            {remaining_member},
        )

        assert result.round_concluded is True
        refreshed = await RoundModel.get(round_id)
        assert refreshed is not None
        assert refreshed.status == RoundStatus.CONCLUDED

    async def it_is_idempotent_on_replay():
        club_id = PydanticObjectId()
        book_id = PydanticObjectId()
        finisher, still_reading = PydanticObjectId(), PydanticObjectId()
        round_ = await _decided_round(club_id, book_id)
        round_id = PydanticObjectId(round_.id)
        current_member_ids = {finisher, still_reading}
        await repo.record_completion(club_id, round_id, book_id, finisher, datetime.now(UTC), current_member_ids)

        result = await repo.record_completion(
            club_id,
            round_id,
            book_id,
            finisher,
            datetime.now(UTC),
            current_member_ids,
        )

        assert result.is_new is False
        assert result.round_concluded is False
        assert await repo.find_user_ids_by_round_id(round_id) == {finisher}

    async def it_does_not_conclude_when_the_round_already_left_decided_before_the_lock_write():
        club_id = PydanticObjectId()
        book_id = PydanticObjectId()
        finisher = PydanticObjectId()
        round_ = await _decided_round(club_id, book_id)
        round_id = PydanticObjectId(round_.id)
        round_.status = RoundStatus.CONCLUDED
        await round_.save()

        result = await repo.record_completion(club_id, round_id, book_id, finisher, datetime.now(UTC), {finisher})

        assert result.is_new is True
        assert result.round_concluded is False
        refreshed = await RoundModel.get(round_id)
        assert refreshed is not None
        assert refreshed.last_completed_by is None
