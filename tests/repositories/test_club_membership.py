from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId

from canterlot.hoodie import link_id
from canterlot.models import ClubMembershipModel, ClubModel
from canterlot.repositories.beanie.club_membership import BeanieClubMembershipRepository
from canterlot.types import MemberRole, MembershipStatus
from tools.factories import ClubFactory, ClubMembershipFactory

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieClubMembershipRepository()


async def _status_of(club_id: PydanticObjectId, user_id: PydanticObjectId) -> MembershipStatus | None:
    membership = await ClubMembershipModel.find_one(
        {"club.$id": club_id},
        {"user.$id": user_id},
    )
    return membership.status if membership else None


def describe_find_member_role_by_club_id_and_user_id():
    async def it_returns_the_members_role():
        club_id = PydanticObjectId()
        member = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.ADMIN,
        )

        role = await repo.find_member_role_by_club_id_and_user_id(club_id, link_id(member.user))

        assert role == MemberRole.ADMIN

    async def it_returns_none_when_the_user_is_not_a_member():
        assert await repo.find_member_role_by_club_id_and_user_id(PydanticObjectId(), PydanticObjectId()) is None

    async def it_returns_none_for_a_pending_row():
        club_id = PydanticObjectId()
        pending = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.PENDING,
        )

        assert await repo.find_member_role_by_club_id_and_user_id(club_id, link_id(pending.user)) is None

    async def it_returns_none_for_a_banned_row():
        club_id = PydanticObjectId()
        banned = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.BANNED,
        )

        assert await repo.find_member_role_by_club_id_and_user_id(club_id, link_id(banned.user)) is None


def describe_exists_by_club_id_and_member_user_id():
    async def it_returns_true_for_an_existing_member():
        club_id = PydanticObjectId()
        member = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )

        assert await repo.exists_by_club_id_and_member_user_id(club_id, link_id(member.user)) is True

    async def it_returns_false_for_a_non_member():
        assert await repo.exists_by_club_id_and_member_user_id(PydanticObjectId(), PydanticObjectId()) is False


def describe_exists_by_club_id_and_pending_user_id():
    async def it_returns_true_for_a_pending_user():
        club_id = PydanticObjectId()
        pending = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.PENDING,
        )

        assert await repo.exists_by_club_id_and_pending_user_id(club_id, link_id(pending.user)) is True

    async def it_returns_false_for_a_non_pending_user():
        assert await repo.exists_by_club_id_and_pending_user_id(PydanticObjectId(), PydanticObjectId()) is False


def describe_exists_by_club_id_and_banned_user_id():
    async def it_returns_true_for_a_banned_user():
        club_id = PydanticObjectId()
        banned = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.BANNED,
        )

        assert await repo.exists_by_club_id_and_banned_user_id(club_id, link_id(banned.user)) is True

    async def it_returns_false_for_a_non_banned_user():
        assert await repo.exists_by_club_id_and_banned_user_id(PydanticObjectId(), PydanticObjectId()) is False


def describe_upsert_member():
    async def it_inserts_a_new_active_membership_row():
        club_id, user_id = PydanticObjectId(), PydanticObjectId()
        joined_at = datetime.now(UTC)

        await repo.upsert_member(club_id, user_id, MemberRole.MEMBER, joined_at)

        assert await _status_of(club_id, user_id) == MembershipStatus.MEMBER

    async def it_promotes_an_existing_banned_row_to_active_in_one_write():
        club_id = PydanticObjectId()
        banned = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.BANNED,
        )

        await repo.upsert_member(club_id, link_id(banned.user), MemberRole.MEMBER, datetime.now(UTC))

        assert await _status_of(club_id, link_id(banned.user)) == MembershipStatus.MEMBER

    async def it_promotes_an_existing_pending_row_to_active():
        club_id = PydanticObjectId()
        pending = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.PENDING,
        )

        await repo.upsert_member(club_id, link_id(pending.user), MemberRole.MEMBER, datetime.now(UTC))

        assert await _status_of(club_id, link_id(pending.user)) == MembershipStatus.MEMBER


def describe_create_pending_request():
    async def it_inserts_a_pending_row():
        club_id, user_id = PydanticObjectId(), PydanticObjectId()
        requested_at = datetime.now(UTC)

        await repo.create_pending_request(club_id, user_id, requested_at)

        membership = await ClubMembershipModel.find_one(
            {"club.$id": club_id},
            {"user.$id": user_id},
        )
        assert membership is not None
        assert membership.status == MembershipStatus.PENDING
        assert membership.requested_at is not None


def describe_delete_membership():
    async def it_removes_the_row_entirely():
        club_id = PydanticObjectId()
        member = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )

        await repo.delete_membership(club_id, link_id(member.user))

        assert await _status_of(club_id, link_id(member.user)) is None


def describe_ban_member():
    async def it_flips_status_to_banned():
        club_id = PydanticObjectId()
        member = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )

        await repo.ban_member(club_id, link_id(member.user))

        assert await _status_of(club_id, link_id(member.user)) == MembershipStatus.BANNED


def describe_change_member_role():
    async def it_changes_the_role_and_persists_it():
        club_id = PydanticObjectId()
        target = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )

        matched = await repo.change_member_role(club_id, link_id(target.user), MemberRole.ADMIN)

        assert matched is True
        assert await _status_of(club_id, link_id(target.user)) == MembershipStatus.ADMIN

    async def it_returns_false_when_the_target_is_the_owner():
        club_id = PydanticObjectId()
        owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.OWNER,
        )

        matched = await repo.change_member_role(club_id, link_id(owner.user), MemberRole.MEMBER)

        assert matched is False
        assert await _status_of(club_id, link_id(owner.user)) == MembershipStatus.OWNER

    async def it_returns_false_when_the_target_is_no_longer_a_member():
        matched = await repo.change_member_role(PydanticObjectId(), PydanticObjectId(), MemberRole.ADMIN)

        assert matched is False


def describe_transfer_ownership():
    async def it_swaps_roles_and_records_transfer_bookkeeping_atomically():
        club = await ClubFactory.create_async()
        club_id = PydanticObjectId(club.id)
        old_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.OWNER,
        )
        new_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )
        transferred_at = datetime.now(UTC)

        matched = await repo.transfer_ownership(
            club_id, link_id(old_owner.user), link_id(new_owner.user), transferred_at
        )

        assert matched is True
        assert await _status_of(club_id, link_id(old_owner.user)) == MembershipStatus.ADMIN
        assert await _status_of(club_id, link_id(new_owner.user)) == MembershipStatus.OWNER

        found_club = await club.get(club_id)
        assert found_club is not None
        assert found_club.protected_former_owner_id == link_id(old_owner.user)
        assert found_club.ownership_transferred_at is not None

    async def it_returns_false_and_leaves_no_partial_write_when_the_caller_is_no_longer_the_owner():
        club = await ClubFactory.create_async()
        club_id = PydanticObjectId(club.id)
        stale_caller = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )
        target = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )

        matched = await repo.transfer_ownership(
            club_id, link_id(stale_caller.user), link_id(target.user), datetime.now(UTC)
        )

        assert matched is False
        # No partial write leaked: both rows are exactly where they started.
        assert await _status_of(club_id, link_id(stale_caller.user)) == MembershipStatus.MEMBER
        assert await _status_of(club_id, link_id(target.user)) == MembershipStatus.MEMBER

        found_club = await club.get(club_id)
        assert found_club is not None
        assert found_club.protected_former_owner_id is None
        assert found_club.ownership_transferred_at is None

    async def it_returns_false_when_the_target_is_not_promotable():
        club = await ClubFactory.create_async()
        club_id = PydanticObjectId(club.id)
        owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.OWNER,
        )
        pending_target = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.PENDING,
        )

        matched = await repo.transfer_ownership(
            club_id, link_id(owner.user), link_id(pending_target.user), datetime.now(UTC)
        )

        assert matched is False
        assert await _status_of(club_id, link_id(owner.user)) == MembershipStatus.OWNER

    async def it_returns_false_and_rolls_back_membership_changes_when_the_club_document_is_missing():
        club_id = PydanticObjectId()
        old_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.OWNER,
        )
        new_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )

        matched = await repo.transfer_ownership(
            club_id, link_id(old_owner.user), link_id(new_owner.user), datetime.now(UTC)
        )

        assert matched is False
        assert await _status_of(club_id, link_id(old_owner.user)) == MembershipStatus.OWNER
        assert await _status_of(club_id, link_id(new_owner.user)) == MembershipStatus.MEMBER


def describe_reclaim_ownership():
    async def it_reverses_roles_and_clears_transfer_bookkeeping():
        transferred_at = datetime.now(UTC)
        club = await ClubFactory.create_async(
            ownership_transferred_at=transferred_at,
        )
        club_id = PydanticObjectId(club.id)
        former_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.ADMIN,
        )
        current_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.OWNER,
        )
        club.protected_former_owner_id = link_id(former_owner.user)
        await club.save()

        matched = await repo.reclaim_ownership(club_id, link_id(former_owner.user), link_id(current_owner.user))

        assert matched is True
        assert await _status_of(club_id, link_id(former_owner.user)) == MembershipStatus.OWNER
        assert await _status_of(club_id, link_id(current_owner.user)) == MembershipStatus.ADMIN

        found_club = await club.get(club_id)
        assert found_club is not None
        assert found_club.ownership_transferred_at is None
        assert found_club.protected_former_owner_id is None

    async def it_returns_false_when_the_stored_former_owner_no_longer_matches():
        club = await ClubFactory.create_async(
            ownership_transferred_at=datetime.now(UTC),
            protected_former_owner_id=PydanticObjectId(),
        )
        club_id = PydanticObjectId(club.id)
        current_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.OWNER,
        )

        matched = await repo.reclaim_ownership(club_id, PydanticObjectId(), link_id(current_owner.user))

        assert matched is False
        assert await _status_of(club_id, link_id(current_owner.user)) == MembershipStatus.OWNER

    async def it_returns_false_and_rolls_back_when_the_current_owner_row_no_longer_matches():
        club = await ClubFactory.create_async(ownership_transferred_at=datetime.now(UTC))
        club_id = PydanticObjectId(club.id)
        former_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.ADMIN,
        )
        club.protected_former_owner_id = link_id(former_owner.user)
        await club.save()
        stale_current_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )

        matched = await repo.reclaim_ownership(club_id, link_id(former_owner.user), link_id(stale_current_owner.user))

        assert matched is False
        assert await _status_of(club_id, link_id(former_owner.user)) == MembershipStatus.ADMIN
        assert await _status_of(club_id, link_id(stale_current_owner.user)) == MembershipStatus.MEMBER

        found_club = await club.get(club_id)
        assert found_club is not None
        assert found_club.protected_former_owner_id == link_id(former_owner.user)

    async def it_returns_false_and_rolls_back_when_the_club_document_no_longer_matches():
        club = await ClubFactory.create_async(
            ownership_transferred_at=datetime.now(UTC),
            protected_former_owner_id=PydanticObjectId(),
        )
        club_id = PydanticObjectId(club.id)
        former_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.ADMIN,
        )
        current_owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.OWNER,
        )

        matched = await repo.reclaim_ownership(club_id, link_id(former_owner.user), link_id(current_owner.user))

        assert matched is False
        assert await _status_of(club_id, link_id(former_owner.user)) == MembershipStatus.ADMIN
        assert await _status_of(club_id, link_id(current_owner.user)) == MembershipStatus.OWNER


def describe_find_active_by_club_id():
    async def it_returns_only_active_rows():
        club_id = PydanticObjectId()
        active = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )
        await ClubMembershipFactory.create_async(club=ClubModel.link_from_id(club_id), status=MembershipStatus.PENDING)
        await ClubMembershipFactory.create_async(club=ClubModel.link_from_id(club_id), status=MembershipStatus.BANNED)

        found = await repo.find_active_by_club_id(club_id)

        assert [link_id(m.user) for m in found] == [link_id(active.user)]


def describe_find_active_membership_by_club_id_and_user_id():
    async def it_returns_the_active_membership():
        club_id = PydanticObjectId()
        member = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )

        found = await repo.find_active_membership_by_club_id_and_user_id(club_id, link_id(member.user))

        assert found is not None
        assert link_id(found.user) == link_id(member.user)

    async def it_returns_none_for_a_pending_row():
        club_id = PydanticObjectId()
        pending = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.PENDING,
        )

        assert await repo.find_active_membership_by_club_id_and_user_id(club_id, link_id(pending.user)) is None


def describe_find_pending_by_club_id():
    async def it_returns_only_pending_rows():
        club_id = PydanticObjectId()
        pending = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.PENDING,
        )
        await ClubMembershipFactory.create_async(club=ClubModel.link_from_id(club_id), status=MembershipStatus.MEMBER)

        found = await repo.find_pending_by_club_id(club_id)

        assert [link_id(m.user) for m in found] == [link_id(pending.user)]


def describe_find_active_member_ids_by_club_id():
    async def it_returns_the_ids_of_active_members_only():
        club_id = PydanticObjectId()
        owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.OWNER,
        )
        member = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.MEMBER,
        )
        await ClubMembershipFactory.create_async(club=ClubModel.link_from_id(club_id), status=MembershipStatus.PENDING)

        found = await repo.find_active_member_ids_by_club_id(club_id)

        assert set(found) == {link_id(owner.user), link_id(member.user)}


def describe_find_owner_id_by_club_id():
    async def it_returns_the_owners_id():
        club_id = PydanticObjectId()
        owner = await ClubMembershipFactory.create_async(
            club=ClubModel.link_from_id(club_id),
            status=MembershipStatus.OWNER,
        )
        await ClubMembershipFactory.create_async(club=ClubModel.link_from_id(club_id), status=MembershipStatus.ADMIN)

        assert await repo.find_owner_id_by_club_id(club_id) == link_id(owner.user)

    async def it_returns_none_when_the_club_has_no_owner_row():
        assert await repo.find_owner_id_by_club_id(PydanticObjectId()) is None
