import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import cast

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
from canterlot.models import BookModel, CatalogEntryModel, ClubModel, RatingStats
from canterlot.models.round import CandidatePoolEntry, DeadlineDuration, RoundModel
from canterlot.repositories import (
    BookRepository,
    CatalogRepository,
    ClubMembershipRepository,
    ReadBookRepository,
    RoundCompletionRepository,
    RoundRepository,
    UserRepository,
)
from canterlot.types import (
    DeadlineType,
    DeadlineUnit,
    MemberRole,
    RoundResolutionMethod,
    RoundSelectionMode,
    RoundStatus,
    UsernameStr,
)
from canterlot.utils import get_logger
from canterlot.utils.weighting import (
    compute_candidate_weights,
    select_top_n_pool,
    weighted_random_draw,
)

logger = get_logger(__name__)


def _add_duration(base: datetime, duration: DeadlineDuration) -> datetime:
    if duration.unit == DeadlineUnit.DAYS:
        return base + timedelta(days=duration.value)
    if duration.unit == DeadlineUnit.WEEKS:
        return base + timedelta(weeks=duration.value)
    return base + relativedelta(months=duration.value)


@dataclass
class RoundDisplay:
    book: BookModel | None
    pool_books: list[BookModel]
    rating_stats: dict[PydanticObjectId, RatingStats]


@dataclass
class MemberProgress:
    username: UsernameStr
    finished: bool


class RoundService:
    def __init__(
        self,
        round_repo: RoundRepository,
        book_repo: BookRepository,
        read_book_repo: ReadBookRepository,
        round_completion_repo: RoundCompletionRepository,
        club_membership_repo: ClubMembershipRepository,
        user_repo: UserRepository,
        catalog_repo: CatalogRepository,
        rng: random.Random | None = None,
    ):
        self.__round_repo = round_repo
        self.__book_repo = book_repo
        self.__read_book_repo = read_book_repo
        self.__round_completion_repo = round_completion_repo
        self.__club_membership_repo = club_membership_repo
        self.__user_repo = user_repo
        self.__catalog_repo = catalog_repo
        self.__rng = rng or random.Random()

    async def start_round(
        self,
        club: ClubModel,
        caller_id: PydanticObjectId,
        payload: StartRoundRequest,
        now: datetime,
    ) -> RoundModel:
        log = logger.bind(
            club_id=str(club.id),
            caller_id=str(caller_id),
            selection_mode=str(payload.selection_mode),
        )
        log.info("Initiating reading round creation")

        club_id = PydanticObjectId(club.id)
        await self.__ensure_caller_is_owner_or_admin(club_id, caller_id, log, action="start a reading round")

        if await self.__round_repo.find_active_by_club_id(club_id) is not None:
            log.warning("Round creation rejected: club already has an active round")
            raise ActiveRoundAlreadyExistsError("This club already has an active reading round.")

        current_member_ids = set(await self.__club_membership_repo.find_active_member_ids_by_club_id(club_id))
        excluded_book_ids = await self.__round_completion_repo.find_majority_excluded_book_ids(
            club_id,
            current_member_ids,
        )
        eligible = await self.__catalog_repo.find_by_club_id_excluding_book_ids(club_id, excluded_book_ids)
        if not eligible:
            log.warning("Round creation rejected: no eligible catalog entries remain")
            raise NoEligibleCatalogError("This club has no eligible books to start a round with.")

        if len(eligible) == 1:
            book_id = eligible[0].book_id
            _, deadline = _resolve_deadline_at_creation(payload.deadline, decided_immediately=True, now=now)
            round_ = RoundModel(
                club_id=club_id,
                selection_mode=payload.selection_mode,
                status=RoundStatus.DECIDED,
                book_id=book_id,
                deadline=deadline,
                started_by=caller_id,
                decided_at=now,
            )
            log.info(
                "Round creation short-circuited: single eligible book locked in immediately",
                book_id=str(book_id),
            )
            return await self.__round_repo.save(round_)

        if payload.selection_mode == RoundSelectionMode.RANDOM:
            weights = await self.__compute_weights(club, eligible, list(current_member_ids), now)
            book_id = weighted_random_draw(self.__rng, weights)
            _, deadline = _resolve_deadline_at_creation(payload.deadline, decided_immediately=True, now=now)
            round_ = RoundModel(
                club_id=club_id,
                selection_mode=RoundSelectionMode.RANDOM,
                status=RoundStatus.DECIDED,
                book_id=book_id,
                deadline=deadline,
                started_by=caller_id,
                decided_at=now,
            )
            log.info("Random round decided immediately", book_id=str(book_id))
            return await self.__round_repo.save(round_)

        weights = await self.__compute_weights(club, eligible, list(current_member_ids), now)
        pool_book_ids = select_top_n_pool(eligible, weights)
        deadline_duration, deadline = _resolve_deadline_at_creation(
            payload.deadline,
            decided_immediately=False,
            now=now,
        )
        round_ = RoundModel(
            club_id=club_id,
            selection_mode=RoundSelectionMode.CURATED,
            status=RoundStatus.SETUP,
            candidate_pool=[CandidatePoolEntry(book_id=book_id) for book_id in pool_book_ids],
            deadline_duration=deadline_duration,
            deadline=deadline,
            started_by=caller_id,
        )
        log.info("Curated round created in setup phase", pool_size=len(pool_book_ids))
        return await self.__round_repo.save(round_)

    async def finalize_round(
        self,
        club: ClubModel,
        caller_id: PydanticObjectId,
        resolution_method: RoundResolutionMethod,
        now: datetime,
    ) -> RoundModel:
        log = logger.bind(
            club_id=str(club.id),
            caller_id=str(caller_id),
            resolution_method=str(resolution_method),
        )
        log.info("Initiating reading round finalize")

        club_id = PydanticObjectId(club.id)
        await self.__ensure_caller_is_owner_or_admin(club_id, caller_id, log, action="finalize a reading round")
        round_ = await self.__get_finalizable_round(club, log)

        if resolution_method == RoundResolutionMethod.DRAW:
            return await self.__finalize_via_draw(club, round_, now, log)

        return await self.__finalize_via_vote(round_, log)

    async def __get_finalizable_round(self, club: ClubModel, log) -> RoundModel:
        round_ = await self.__round_repo.find_active_by_club_id(PydanticObjectId(club.id))
        if round_ is None:
            log.warning("Finalize rejected: no active round exists")
            raise RoundNotFoundError("This club has no active reading round.")

        if round_.status != RoundStatus.SETUP:
            log.warning("Finalize rejected: round is not in its setup phase", round_status=str(round_.status))
            raise RoundAlreadyFinalizedError("This round has already been finalized.")

        return round_

    async def __finalize_via_draw(self, club: ClubModel, round_: RoundModel, now: datetime, log) -> RoundModel:
        round_id = PydanticObjectId(round_.id)
        club_id = PydanticObjectId(club.id)
        pool_book_ids = {entry.book_id for entry in round_.candidate_pool}
        pool_entries = await self.__catalog_repo.find_by_club_id_and_book_ids(club_id, pool_book_ids)
        member_ids = await self.__club_membership_repo.find_active_member_ids_by_club_id(club_id)
        weights = await self.__compute_weights(club, pool_entries, member_ids, now)
        book_id = weighted_random_draw(self.__rng, weights)
        deadline = _add_duration(now, round_.deadline_duration) if round_.deadline_duration else None

        changed = await self.__round_repo.finalize_with_draw(round_id, book_id, now, deadline)
        if not changed:
            log.warning("Finalize rejected: round state changed before the draw could complete")
            raise RoundAlreadyFinalizedError("This round has already been finalized.")

        round_.status = RoundStatus.DECIDED
        round_.resolution_method = RoundResolutionMethod.DRAW
        round_.book_id = book_id
        round_.decided_at = now
        if deadline is not None:
            round_.deadline = deadline

        log.info("Round finalized via weighted draw", book_id=str(book_id))
        return round_

    async def __finalize_via_vote(self, round_: RoundModel, log) -> RoundModel:
        changed = await self.__round_repo.finalize_with_vote(PydanticObjectId(round_.id))
        if not changed:
            log.warning("Finalize rejected: round state changed before voting could open")
            raise RoundAlreadyFinalizedError("This round has already been finalized.")

        round_.status = RoundStatus.VOTING
        round_.resolution_method = RoundResolutionMethod.VOTE

        log.info("Round finalized: voting opened")
        return round_

    async def resolve_display(self, round_: RoundModel) -> RoundDisplay:
        book_ids = {entry.book_id for entry in round_.candidate_pool}
        if round_.book_id is not None:
            book_ids.add(round_.book_id)

        if not book_ids:
            return RoundDisplay(book=None, pool_books=[], rating_stats={})

        book_id_list = list(book_ids)
        books_by_id = await self.__book_repo.find_by_ids(book_id_list)
        rating_stats = await self.__read_book_repo.find_rating_stats_by_book_ids(book_id_list)

        book = books_by_id.get(round_.book_id) if round_.book_id is not None else None
        pool_books = [books_by_id[entry.book_id] for entry in round_.candidate_pool]

        return RoundDisplay(book=book, pool_books=pool_books, rating_stats=rating_stats)

    async def get_progress(self, club_id: PydanticObjectId, caller_id: PydanticObjectId) -> list[MemberProgress]:
        log = logger.bind(club_id=str(club_id), caller_id=str(caller_id))
        await self.__ensure_caller_is_member(club_id, caller_id, log, action="view this club's reading progress")
        round_ = await self.__get_decided_round(club_id, log)

        current_member_ids = await self.__club_membership_repo.find_active_member_ids_by_club_id(club_id)
        finished_user_ids = await self.__round_completion_repo.find_user_ids_by_round_id(PydanticObjectId(round_.id))
        usernames_by_id = await self.__user_repo.get_usernames_by_ids(current_member_ids)

        log.info("Round progress resolved", member_count=len(current_member_ids))
        return sorted(
            (
                MemberProgress(username=usernames_by_id[user_id], finished=user_id in finished_user_ids)
                for user_id in current_member_ids
            ),
            key=lambda entry: entry.username,
        )

    async def mark_finished(
        self,
        club_id: PydanticObjectId,
        caller_id: PydanticObjectId,
        rating: float | None,
        now: datetime,
    ) -> None:
        log = logger.bind(club_id=str(club_id), caller_id=str(caller_id), rating=rating)
        log.info("Marking round finished")

        await self.__ensure_caller_is_member(club_id, caller_id, log, action="mark a book finished")
        round_ = await self.__get_decided_round(club_id, log)
        book_id = cast(PydanticObjectId, round_.book_id)

        current_member_ids = set(await self.__club_membership_repo.find_active_member_ids_by_club_id(club_id))
        result = await self.__round_completion_repo.record_completion(
            club_id,
            PydanticObjectId(round_.id),
            book_id,
            caller_id,
            now,
            current_member_ids,
        )
        await self.__read_book_repo.upsert(caller_id, book_id, rating)

        if result.round_concluded:
            log.info("Round auto-closed: every current member has finished")
        log.info("Round marked finished for member", is_new=result.is_new)

    async def __get_decided_round(self, club_id: PydanticObjectId, log) -> RoundModel:
        round_ = await self.__round_repo.find_active_by_club_id(club_id)
        if round_ is None or round_.status != RoundStatus.DECIDED:
            log.warning("Rejected: no active round with a decided book")
            raise RoundNotFoundError("This club has no active reading round with a decided book.")

        return round_

    async def __ensure_caller_is_member(
        self,
        club_id: PydanticObjectId,
        caller_id: PydanticObjectId,
        log,
        action: str,
    ) -> None:
        if not await self.__club_membership_repo.exists_by_club_id_and_member_user_id(club_id, caller_id):
            log.warning("Rejected: caller is not a club member", action=action)
            raise UnauthorizedClubMemberError(f"Only members of this club can {action}.")

    async def __ensure_caller_is_owner_or_admin(
        self,
        club_id: PydanticObjectId,
        caller_id: PydanticObjectId,
        log,
        action: str,
    ) -> None:
        caller_role = await self.__club_membership_repo.find_member_role_by_club_id_and_user_id(club_id, caller_id)
        if caller_role is None or caller_role not in (MemberRole.OWNER, MemberRole.ADMIN):
            log.warning("Rejected: caller lacks OWNER/ADMIN privileges", action=action)
            raise UnauthorizedClubMemberError(f"Only an OWNER or ADMIN can {action}.")

    async def __compute_weights(
        self,
        club: ClubModel,
        entries: list[CatalogEntryModel],
        member_ids: list[PydanticObjectId],
        now: datetime,
    ) -> dict[PydanticObjectId, float]:
        book_ids = [entry.book_id for entry in entries]

        books_by_id = await self.__book_repo.find_by_ids(book_ids)
        rating_stats = await self.__read_book_repo.find_rating_stats_by_book_ids(book_ids)
        familiarity_counts = await self.__read_book_repo.count_readers_among_users(book_ids, member_ids)

        return compute_candidate_weights(
            entries=entries,
            preferred_languages=club.preferred_languages,
            familiarity_counts=familiarity_counts,
            current_member_count=len(member_ids),
            rating_stats_by_book=rating_stats,
            books_by_id=books_by_id,
            now=now,
        )


def _resolve_deadline_at_creation(
    deadline_request: DeadlineRequest | None,
    decided_immediately: bool,
    now: datetime,
) -> tuple[DeadlineDuration | None, datetime | None]:
    if deadline_request is None:
        return None, None

    if deadline_request.type == DeadlineType.CUSTOM:
        target_date = cast(date, deadline_request.target_date)
        target_datetime = datetime.combine(target_date, time.min, tzinfo=UTC)
        return None, target_datetime

    duration = DeadlineDuration(value=cast(int, deadline_request.value), unit=cast(DeadlineUnit, deadline_request.unit))
    if not decided_immediately:
        return duration, None

    return None, _add_duration(now, duration)
