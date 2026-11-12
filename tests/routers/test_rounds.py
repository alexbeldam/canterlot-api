from unittest.mock import AsyncMock

from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.exceptions import (
    ActiveRoundAlreadyExistsError,
    ClubNotFoundError,
    NoEligibleCatalogError,
    RoundAlreadyFinalizedError,
    RoundNotFoundError,
    UnauthorizedClubMemberError,
)
from canterlot.services.round import MemberProgress, RoundDisplay
from canterlot.types import RoundResolutionMethod, RoundSelectionMode, RoundStatus
from tools.factories import BookFactory, ClubFactory, RoundFactory

SOME_CLUB_SLUG = "book-club"
SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439020")
SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def _round(**overrides):
    defaults = {
        "club_id": PydanticObjectId(),
        "started_by": PydanticObjectId(),
        "selection_mode": RoundSelectionMode.RANDOM,
        "status": RoundStatus.DECIDED,
        "book_id": SOME_BOOK_ID,
        "candidate_pool": [],
    }
    defaults.update(overrides)
    return RoundFactory.build(**defaults)


def describe_start_reading_round():
    def it_creates_a_round_and_returns_201_with_a_location_header(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_by_slug.return_value = ClubFactory.build(slug=SOME_CLUB_SLUG)
        round_service.start_round.return_value = _round()
        round_service.resolve_display.return_value = RoundDisplay(
            book=BookFactory.build(id=SOME_BOOK_ID),
            pool_books=[],
            rating_stats={},
        )

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/rounds", json={"selection_mode": "RANDOM"})

        assert response.status_code == 201
        assert response.headers["Location"] == f"/v1/clubs/{SOME_CLUB_SLUG}/round"
        body = response.json()
        assert body["status"] == "DECIDED"
        assert body["book"]["external_id"]
        assert "id" not in body

    def it_returns_403_when_caller_lacks_owner_or_admin_rank(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_by_slug.return_value = ClubFactory.build(slug=SOME_CLUB_SLUG)
        round_service.start_round.side_effect = UnauthorizedClubMemberError("Only an OWNER or ADMIN can start.")

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/rounds", json={"selection_mode": "RANDOM"})

        assert response.status_code == 403

    def it_returns_404_when_the_club_does_not_exist(client: TestClient, club_service: AsyncMock):
        club_service.get_club_by_slug.side_effect = ClubNotFoundError("This club no longer exists.")

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/rounds", json={"selection_mode": "RANDOM"})

        assert response.status_code == 404

    def it_returns_409_when_an_active_round_already_exists(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_by_slug.return_value = ClubFactory.build(slug=SOME_CLUB_SLUG)
        round_service.start_round.side_effect = ActiveRoundAlreadyExistsError("Already active.")

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/rounds", json={"selection_mode": "RANDOM"})

        assert response.status_code == 409

    def it_returns_409_when_the_eligible_catalog_is_empty(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_by_slug.return_value = ClubFactory.build(slug=SOME_CLUB_SLUG)
        round_service.start_round.side_effect = NoEligibleCatalogError("No eligible books.")

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/rounds", json={"selection_mode": "CURATED"})

        assert response.status_code == 409

    def it_returns_a_populated_candidate_pool_for_a_curated_round(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_by_slug.return_value = ClubFactory.build(slug=SOME_CLUB_SLUG)
        pool_book = BookFactory.build()
        round_service.start_round.return_value = _round(
            selection_mode=RoundSelectionMode.CURATED,
            status=RoundStatus.SETUP,
            book_id=None,
            candidate_pool=[pool_book.to_link()],
        )
        round_service.resolve_display.return_value = RoundDisplay(book=None, pool_books=[pool_book], rating_stats={})

        response = client.post(f"/v1/clubs/{SOME_CLUB_SLUG}/rounds", json={"selection_mode": "CURATED"})

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "SETUP"
        assert body["book"] is None
        assert len(body["candidate_pool"]) == 1


def describe_finalize_reading_round():
    def it_returns_200_with_the_decided_book_when_finalizing_via_draw(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_by_slug.return_value = ClubFactory.build(slug=SOME_CLUB_SLUG)
        round_service.finalize_round.return_value = _round(
            selection_mode=RoundSelectionMode.CURATED,
            status=RoundStatus.DECIDED,
            resolution_method=RoundResolutionMethod.DRAW,
        )
        round_service.resolve_display.return_value = RoundDisplay(
            book=BookFactory.build(id=SOME_BOOK_ID),
            pool_books=[],
            rating_stats={},
        )

        response = client.patch(
            f"/v1/clubs/{SOME_CLUB_SLUG}/round",
            json={"resolution_method": "DRAW"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "DECIDED"
        assert body["resolution_method"] == "DRAW"
        assert body["book"] is not None

    def it_returns_200_with_voting_open_when_finalizing_via_vote(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_by_slug.return_value = ClubFactory.build(slug=SOME_CLUB_SLUG)
        round_service.finalize_round.return_value = _round(
            selection_mode=RoundSelectionMode.CURATED,
            status=RoundStatus.VOTING,
            resolution_method=RoundResolutionMethod.VOTE,
            book_id=None,
        )
        round_service.resolve_display.return_value = RoundDisplay(book=None, pool_books=[], rating_stats={})

        response = client.patch(
            f"/v1/clubs/{SOME_CLUB_SLUG}/round",
            json={"resolution_method": "VOTE"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "VOTING"
        assert body["book"] is None

    def it_returns_404_when_no_active_round_exists(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_by_slug.return_value = ClubFactory.build(slug=SOME_CLUB_SLUG)
        round_service.finalize_round.side_effect = RoundNotFoundError("No active round.")

        response = client.patch(
            f"/v1/clubs/{SOME_CLUB_SLUG}/round",
            json={"resolution_method": "DRAW"},
        )

        assert response.status_code == 404

    def it_returns_409_when_the_round_is_already_finalized(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_by_slug.return_value = ClubFactory.build(slug=SOME_CLUB_SLUG)
        round_service.finalize_round.side_effect = RoundAlreadyFinalizedError("Already finalized.")

        response = client.patch(
            f"/v1/clubs/{SOME_CLUB_SLUG}/round",
            json={"resolution_method": "DRAW"},
        )

        assert response.status_code == 409

    def it_returns_403_when_caller_lacks_owner_or_admin_rank(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_by_slug.return_value = ClubFactory.build(slug=SOME_CLUB_SLUG)
        round_service.finalize_round.side_effect = UnauthorizedClubMemberError("Not allowed.")

        response = client.patch(
            f"/v1/clubs/{SOME_CLUB_SLUG}/round",
            json={"resolution_method": "DRAW"},
        )

        assert response.status_code == 403


def describe_get_round_progress():
    def it_returns_every_current_members_finished_state(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_id_by_slug.return_value = PydanticObjectId()
        round_service.get_progress.return_value = [
            MemberProgress(username="alice", finished=True),
            MemberProgress(username="bob", finished=False),
        ]

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/round/progress")

        assert response.status_code == 200
        assert response.json() == {
            "entries": [
                {"username": "alice", "finished": True},
                {"username": "bob", "finished": False},
            ]
        }

    def it_returns_404_when_the_club_does_not_exist(client: TestClient, club_service: AsyncMock):
        club_service.get_club_id_by_slug.side_effect = ClubNotFoundError("This club no longer exists.")

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/round/progress")

        assert response.status_code == 404

    def it_returns_404_when_no_decided_round_exists(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_id_by_slug.return_value = PydanticObjectId()
        round_service.get_progress.side_effect = RoundNotFoundError("No active round.")

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/round/progress")

        assert response.status_code == 404

    def it_returns_403_when_caller_is_not_a_member(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_id_by_slug.return_value = PydanticObjectId()
        round_service.get_progress.side_effect = UnauthorizedClubMemberError("Not a member.")

        response = client.get(f"/v1/clubs/{SOME_CLUB_SLUG}/round/progress")

        assert response.status_code == 403


def describe_mark_round_finished():
    def it_marks_the_caller_finished_and_returns_204(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_id_by_slug.return_value = PydanticObjectId()

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/round/me", json={"rating": 4.5})

        assert response.status_code == 204
        round_service.mark_finished.assert_awaited_once()
        args = round_service.mark_finished.await_args.args
        assert args[1] == SOME_USER_ID
        assert args[2] == 4.5

    def it_allows_an_empty_body_with_no_rating(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_id_by_slug.return_value = PydanticObjectId()

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/round/me")

        assert response.status_code == 204
        args = round_service.mark_finished.await_args.args
        assert args[2] is None

    def it_returns_404_when_the_club_does_not_exist(client: TestClient, club_service: AsyncMock):
        club_service.get_club_id_by_slug.side_effect = ClubNotFoundError("This club no longer exists.")

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/round/me")

        assert response.status_code == 404

    def it_returns_404_when_no_decided_round_exists(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_id_by_slug.return_value = PydanticObjectId()
        round_service.mark_finished.side_effect = RoundNotFoundError("No active round.")

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/round/me")

        assert response.status_code == 404

    def it_returns_403_when_caller_is_not_a_member(
        client: TestClient,
        club_service: AsyncMock,
        round_service: AsyncMock,
    ):
        club_service.get_club_id_by_slug.return_value = PydanticObjectId()
        round_service.mark_finished.side_effect = UnauthorizedClubMemberError("Not a member.")

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/round/me")

        assert response.status_code == 403

    def it_returns_422_for_an_out_of_range_rating(client: TestClient, club_service: AsyncMock):
        club_service.get_club_id_by_slug.return_value = PydanticObjectId()

        response = client.put(f"/v1/clubs/{SOME_CLUB_SLUG}/round/me", json={"rating": 6.0})

        assert response.status_code == 422
