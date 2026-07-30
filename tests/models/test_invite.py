from beanie import PydanticObjectId

from canterlot.models.invite import InviteModel
from canterlot.types import InviteType
from tools.factories import InviteFactory


def describe_invite_model_defaults():
    def it_generates_a_short_random_id_by_default():
        invite = InviteFactory.build()
        assert len(invite.id) == 10

    def it_generates_distinct_ids_across_instances():
        first = InviteFactory.build()
        second = InviteFactory.build()
        assert first.id != second.id

    def it_defaults_to_a_public_active_invite():
        invite = InviteModel(club_id=PydanticObjectId())
        assert invite.type == InviteType.PUBLIC
        assert invite.is_active is True
        assert invite.uses_count == 0
        assert invite.target_email is None


def describe_invite_model_target_email_normalization():
    def it_normalizes_the_target_email():
        invite = InviteFactory.build(target_email="  Alice@Example.COM  ", type=InviteType.DIRECT)
        assert invite.target_email == "alice@example.com"
