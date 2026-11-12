from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId
from bson import DBRef
from pydantic import SecretStr
from pymongo.errors import DuplicateKeyError

from canterlot.hoodie import link_id
from canterlot.models import (
    BookModel,
    CatalogEntryModel,
    ClubMembershipModel,
    ClubModel,
    InviteModel,
    ReadBookModel,
    RoundCompletionModel,
    RoundModel,
    UserModel,
    VerificationCodeModel,
)
from canterlot.repositories.beanie.round_completion import BeanieRoundCompletionRepository
from canterlot.repositories.beanie.verification import BeanieVerificationRepository
from canterlot.types import InviteType, MembershipStatus, RoundSelectionMode, RoundStatus, VerificationScope
from tools.factories import (
    BookFactory,
    CatalogEntryFactory,
    ClubFactory,
    ClubMembershipFactory,
    InviteFactory,
    ReadBookFactory,
    RoundCompletionFactory,
    RoundFactory,
    UserFactory,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _id(document) -> PydanticObjectId:
    return PydanticObjectId(document.id)


async def _raw(model, document_id):
    return await model.get_pymongo_collection().find_one({"_id": document_id})


async def _index_keys(model) -> dict[str, list[str]]:
    info = await model.get_pymongo_collection().index_information()
    return {name: [field for field, _ in spec["key"]] for name, spec in info.items()}


def describe_stored_shape():
    async def it_stores_every_relationship_as_a_dbref():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()

        entry = await CatalogEntryFactory.create_async(
            club=club.to_link(),
            book=book.to_link(),
            suggested_by=user.to_link(),
        )

        raw = await _raw(CatalogEntryModel, entry.id)
        assert raw["club"] == DBRef("clubs", _id(club))
        assert raw["book"] == DBRef("books", _id(book))
        assert raw["suggested_by"] == DBRef("users", _id(user))

    async def it_stores_a_missing_optional_link_as_null():
        club = await ClubFactory.create_async()

        invite = await InviteFactory.create_async(club=club.to_link(), type=InviteType.PUBLIC)

        raw = await _raw(InviteModel, invite.id)
        assert raw["created_by"] is None
        assert raw["target_user"] is None

    async def it_stores_the_candidate_pool_as_a_list_of_dbrefs():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        books = [await BookFactory.create_async() for _ in range(2)]

        round_ = await RoundFactory.create_async(
            club=club.to_link(),
            started_by=user.to_link(),
            selection_mode=RoundSelectionMode.CURATED,
            status=RoundStatus.SETUP,
            candidate_pool=[book.to_link() for book in books],
        )

        raw = await _raw(RoundModel, round_.id)
        assert raw["candidate_pool"] == [DBRef("books", _id(book)) for book in books]

    async def it_stores_a_verification_code_owner_as_a_dbref():
        user = await UserFactory.create_async()
        code = VerificationCodeModel.build(SecretStr("123456"), _id(user), VerificationScope.EMAIL)

        await code.insert()

        raw = await _raw(VerificationCodeModel, code.id)
        assert raw["user"] == DBRef("users", _id(user))

    async def it_stores_a_completion_written_by_the_upsert_path_as_dbrefs():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()
        round_ = await RoundFactory.create_async(
            club=club.to_link(),
            started_by=user.to_link(),
            status=RoundStatus.DECIDED,
            book=book.to_link(),
        )

        await BeanieRoundCompletionRepository().record_completion(
            _id(club),
            _id(round_),
            _id(book),
            _id(user),
            datetime.now(UTC),
            {_id(user)},
        )

        raw = await RoundCompletionModel.get_pymongo_collection().find_one({"user.$id": _id(user)})
        assert raw is not None
        assert raw["club"] == DBRef("clubs", _id(club))
        assert raw["round"] == DBRef("reading_rounds", _id(round_))
        assert raw["book"] == DBRef("books", _id(book))
        assert raw["user"] == DBRef("users", _id(user))

    async def it_keeps_the_owner_dbref_after_the_raw_attempt_counter_write():
        user = await UserFactory.create_async()
        code = VerificationCodeModel.build(SecretStr("123456"), _id(user), VerificationScope.EMAIL)
        await code.insert()

        await BeanieVerificationRepository().increment_attempts_and_burn_if_exceeded(_id(user), VerificationScope.EMAIL)

        raw = await _raw(VerificationCodeModel, code.id)
        assert raw["attempts"] == 1
        assert raw["user"] == DBRef("users", _id(user))


def describe_backlinks():
    async def it_populates_a_club_with_its_memberships_catalog_entries_and_invites():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()
        club_link = club.to_link()
        await ClubMembershipFactory.create_async(club=club_link, user=user.to_link(), status=MembershipStatus.MEMBER)
        await CatalogEntryFactory.create_async(club=club_link, book=book.to_link(), suggested_by=user.to_link())
        await InviteFactory.create_async(club=club_link, type=InviteType.PUBLIC)

        fetched = await ClubModel.get(club.id, fetch_links=True)

        assert fetched is not None
        assert len(fetched.memberships) == 1
        assert len(fetched.catalog_entries) == 1
        assert len(fetched.invites) == 1

    async def it_populates_a_user_with_its_memberships():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        await ClubMembershipFactory.create_async(
            club=club.to_link(),
            user=user.to_link(),
            status=MembershipStatus.MEMBER,
        )

        fetched = await UserModel.get(user.id, fetch_links=True)

        assert fetched is not None
        assert len(fetched.memberships) == 1

    async def it_populates_a_book_with_its_catalog_entries():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()
        await CatalogEntryFactory.create_async(
            club=club.to_link(),
            book=book.to_link(),
            suggested_by=user.to_link(),
        )

        fetched = await BookModel.get(book.id, fetch_links=True)

        assert fetched is not None
        assert len(fetched.catalog_entries) == 1

    async def it_populates_a_round_with_its_completions():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()
        round_ = await RoundFactory.create_async(
            club=club.to_link(),
            started_by=user.to_link(),
            status=RoundStatus.DECIDED,
            book=book.to_link(),
        )
        await RoundCompletionFactory.create_async(
            club=club.to_link(),
            round=round_.to_link(),
            book=book.to_link(),
            user=user.to_link(),
        )

        fetched = await RoundModel.get(round_.id, fetch_links=True)

        assert fetched is not None
        assert len(fetched.completions) == 1

    async def it_excludes_backlinks_from_the_stored_document():
        club = await ClubFactory.create_async()

        raw = await _raw(ClubModel, club.id)

        assert "memberships" not in raw
        assert "catalog_entries" not in raw
        assert "invites" not in raw


def describe_link_id_on_fetched_links():
    async def it_reads_the_related_id_after_the_link_is_fetched():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        membership = await ClubMembershipFactory.create_async(
            club=club.to_link(),
            user=user.to_link(),
            status=MembershipStatus.MEMBER,
        )

        fetched = await ClubMembershipModel.get(membership.id, fetch_links=True)

        assert fetched is not None
        assert link_id(fetched.club) == _id(club)
        assert link_id(fetched.user) == _id(user)


def describe_indexes():
    async def it_indexes_catalog_entries_over_link_ids():
        keys = await _index_keys(CatalogEntryModel)

        assert keys["unique_club_book_idx"] == ["club.$id", "book.$id"]
        assert keys["club_suggested_at_idx"] == ["club.$id", "suggested_at"]

    async def it_indexes_memberships_over_link_ids():
        keys = await _index_keys(ClubMembershipModel)

        assert keys["unique_club_user_idx"] == ["club.$id", "user.$id"]
        assert keys["user_membership_idx"] == ["user.$id"]

    async def it_indexes_read_books_over_link_ids():
        keys = await _index_keys(ReadBookModel)

        assert keys["unique_user_book_idx"] == ["user.$id", "book.$id"]

    async def it_indexes_invites_over_link_ids():
        keys = await _index_keys(InviteModel)

        assert keys["club_invite_lookup_idx"] == [
            "club.$id",
            "type",
            "is_active",
            "target_email",
            "target_user.$id",
        ]

    async def it_indexes_rounds_over_link_ids():
        keys = await _index_keys(RoundModel)

        assert keys["club_active_round_idx"] == ["club.$id", "status"]

    async def it_indexes_round_completions_over_link_ids():
        keys = await _index_keys(RoundCompletionModel)

        assert keys["unique_round_user_completion_idx"] == ["round.$id", "user.$id"]
        assert keys["club_book_completion_idx"] == ["club.$id", "book.$id"]

    async def it_indexes_verification_codes_over_link_ids():
        keys = await _index_keys(VerificationCodeModel)

        assert keys["user_scope_hash_lookup_idx"] == ["user.$id", "scope", "code_hash", "is_active"]

    async def it_uses_the_membership_index_for_a_link_id_lookup():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        await ClubMembershipFactory.create_async(
            club=club.to_link(),
            user=user.to_link(),
            status=MembershipStatus.MEMBER,
        )

        query_filter = ClubMembershipModel.find({"club.$id": _id(club)}).get_filter_query()
        plan = await ClubMembershipModel.get_pymongo_collection().find(query_filter).explain()

        assert "IXSCAN" in str(plan["queryPlanner"]["winningPlan"])


def describe_uniqueness():
    async def it_rejects_a_duplicate_club_book_catalog_entry():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()
        fields = {
            "club": club.to_link(),
            "book": book.to_link(),
            "suggested_by": user.to_link(),
        }
        await CatalogEntryFactory.create_async(**fields)

        with pytest.raises(DuplicateKeyError):
            await CatalogEntryFactory.create_async(**fields)

    async def it_rejects_a_duplicate_club_user_membership():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        fields = {
            "club": club.to_link(),
            "user": user.to_link(),
            "status": MembershipStatus.MEMBER,
        }
        await ClubMembershipFactory.create_async(**fields)

        with pytest.raises(DuplicateKeyError):
            await ClubMembershipFactory.create_async(**fields)

    async def it_rejects_a_duplicate_user_book_read_entry():
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()
        fields = {"user": user.to_link(), "book": book.to_link()}
        await ReadBookFactory.create_async(**fields)

        with pytest.raises(DuplicateKeyError):
            await ReadBookFactory.create_async(**fields)

    async def it_rejects_a_duplicate_round_user_completion():
        club = await ClubFactory.create_async()
        user = await UserFactory.create_async()
        book = await BookFactory.create_async()
        round_ = await RoundFactory.create_async(
            club=club.to_link(),
            started_by=user.to_link(),
            status=RoundStatus.DECIDED,
            book=book.to_link(),
        )
        fields = {
            "club": club.to_link(),
            "round": round_.to_link(),
            "book": book.to_link(),
            "user": user.to_link(),
        }
        await RoundCompletionFactory.create_async(**fields)

        with pytest.raises(DuplicateKeyError):
            await RoundCompletionFactory.create_async(**fields)
