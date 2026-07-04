from beanie import PydanticObjectId

from canterlot.models.enums import InviteType, JoinPolicy
from canterlot.models.invite import InviteModel, InvitePreviewResponse

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def describe_invite_model_defaults():
    def it_generates_a_short_random_id_by_default():
        invite = InviteModel(club_id=SOME_CLUB_ID)
        assert len(invite.id) == 10

    def it_generates_distinct_ids_across_instances():
        first = InviteModel(club_id=SOME_CLUB_ID)
        second = InviteModel(club_id=SOME_CLUB_ID)
        assert first.id != second.id

    def it_defaults_to_a_public_active_invite():
        invite = InviteModel(club_id=SOME_CLUB_ID)
        assert invite.type == InviteType.PUBLIC
        assert invite.is_active is True
        assert invite.uses_count == 0
        assert invite.target_email is None


def describe_invite_model_target_email_normalization():
    def it_normalizes_the_target_email():
        invite = InviteModel(club_id=SOME_CLUB_ID, target_email="  Alice@Example.COM  ")
        assert invite.target_email == "alice@example.com"


def describe_invite_preview_response():
    def it_allows_an_absent_invited_by_username():
        preview = InvitePreviewResponse(
            club_id=SOME_CLUB_ID,
            club_name="Book Club",
            join_policy=JoinPolicy.PUBLIC,
            invite_type=InviteType.DIRECT,
        )
        assert preview.invited_by_username is None
