import pytest
from beanie import PydanticObjectId

from canterlot.models.enums import InviteType
from canterlot.models.invite import InviteModel
from canterlot.repositories.beanie.invite import BeanieInviteRepository

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieInviteRepository()


async def _invite(**overrides: object) -> InviteModel:
    defaults = {"club_id": PydanticObjectId()}
    return await InviteModel(**{**defaults, **overrides}).insert()


def describe_find_by_id():
    async def it_finds_an_invite_by_id():
        invite = await _invite()

        found = await repo.find_by_id(invite.id)

        assert found is not None
        assert found.club_id == invite.club_id

    async def it_returns_none_when_the_invite_does_not_exist():
        assert await repo.find_by_id("no-such-id") is None


def describe_find_one_active_public_by_club_id():
    async def it_finds_the_active_public_invite():
        club_id = PydanticObjectId()
        invite = await _invite(club_id=club_id, type=InviteType.PUBLIC, is_active=True)

        found = await repo.find_one_active_public_by_club_id(club_id)

        assert found is not None
        assert found.id == invite.id

    async def it_ignores_an_inactive_public_invite():
        club_id = PydanticObjectId()
        await _invite(club_id=club_id, type=InviteType.PUBLIC, is_active=False)

        assert await repo.find_one_active_public_by_club_id(club_id) is None

    async def it_ignores_a_direct_invite():
        club_id = PydanticObjectId()
        await _invite(club_id=club_id, type=InviteType.DIRECT, is_active=True, target_email="a@example.com")

        assert await repo.find_one_active_public_by_club_id(club_id) is None


def describe_find_by_club_id():
    async def it_returns_every_invite_for_the_club():
        club_id = PydanticObjectId()
        first = await _invite(club_id=club_id)
        second = await _invite(club_id=club_id)
        await _invite(club_id=PydanticObjectId())

        found = await repo.find_by_club_id(club_id)

        assert {invite.id for invite in found} == {first.id, second.id}

    async def it_returns_an_empty_list_when_the_club_has_no_invites():
        assert await repo.find_by_club_id(PydanticObjectId()) == []


def describe_save():
    async def it_persists_changes_to_an_existing_invite():
        invite = await _invite()

        invite.uses_count = 5
        await repo.save(invite)

        found = await repo.find_by_id(invite.id)
        assert found is not None
        assert found.uses_count == 5


def describe_increment_uses_count_by_id():
    async def it_increments_the_uses_count():
        invite = await _invite(uses_count=1)

        await repo.increment_uses_count_by_id(invite.id)

        found = await repo.find_by_id(invite.id)
        assert found is not None
        assert found.uses_count == 2


def describe_deactivate_by_id():
    async def it_marks_the_invite_inactive():
        invite = await _invite(is_active=True)

        await repo.deactivate_by_id(invite.id)

        found = await repo.find_by_id(invite.id)
        assert found is not None
        assert found.is_active is False


def describe_deactivate_all_public_by_club_id():
    async def it_deactivates_only_active_public_invites_for_the_club():
        club_id = PydanticObjectId()
        public = await _invite(club_id=club_id, type=InviteType.PUBLIC, is_active=True)
        direct = await _invite(club_id=club_id, type=InviteType.DIRECT, is_active=True, target_email="a@example.com")
        other_club_public = await _invite(club_id=PydanticObjectId(), type=InviteType.PUBLIC, is_active=True)

        await repo.deactivate_all_public_by_club_id(club_id)

        assert (await repo.find_by_id(public.id)).is_active is False  # type: ignore[union-attr]
        assert (await repo.find_by_id(direct.id)).is_active is True  # type: ignore[union-attr]
        assert (await repo.find_by_id(other_club_public.id)).is_active is True  # type: ignore[union-attr]


def describe_dactivate_all_direct_by_club_id_and_target_email():
    async def it_deactivates_only_matching_direct_invites():
        club_id = PydanticObjectId()
        matching = await _invite(
            club_id=club_id, type=InviteType.DIRECT, is_active=True, target_email="target@example.com"
        )
        other_email = await _invite(
            club_id=club_id, type=InviteType.DIRECT, is_active=True, target_email="other@example.com"
        )
        public = await _invite(club_id=club_id, type=InviteType.PUBLIC, is_active=True)

        await repo.dactivate_all_direct_by_club_id_and_target_email(club_id, "target@example.com")

        assert (await repo.find_by_id(matching.id)).is_active is False  # type: ignore[union-attr]
        assert (await repo.find_by_id(other_email.id)).is_active is True  # type: ignore[union-attr]
        assert (await repo.find_by_id(public.id)).is_active is True  # type: ignore[union-attr]
