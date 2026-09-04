import pytest
from beanie import PydanticObjectId
from pydantic import ValidationError

from canterlot.models.club import PendingApprovalSchema
from tools.factories import ClubFactory, MemberFactory

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def describe_club_name_constraints():
    @pytest.mark.parametrize("bad_name", ["ab", "a" * 51, "  "])
    def it_rejects_names_outside_the_length_bounds(bad_name: str):
        with pytest.raises(ValidationError):
            ClubFactory.build(name=bad_name)

    def it_accepts_a_name_within_bounds():
        assert ClubFactory.build(name="Book Club").name == "Book Club"


def describe_membership_state_exclusivity():
    def it_rejects_a_user_who_is_both_an_active_member_and_banned():
        with pytest.raises(ValidationError, match="active members and banned"):
            ClubFactory.build(
                members=[MemberFactory.build(user_id=SOME_USER_ID)],
                banned_users=[SOME_USER_ID],
            )

    def it_rejects_a_user_who_is_both_an_active_member_and_pending():
        with pytest.raises(ValidationError, match="active members and pending"):
            ClubFactory.build(
                members=[MemberFactory.build(user_id=SOME_USER_ID)],
                pending_approvals=[PendingApprovalSchema(user_id=SOME_USER_ID)],
            )

    def it_rejects_a_user_who_is_both_banned_and_pending():
        with pytest.raises(ValidationError, match="banned and pending approval"):
            ClubFactory.build(
                banned_users=[SOME_USER_ID],
                pending_approvals=[PendingApprovalSchema(user_id=SOME_USER_ID)],
            )

    def it_accepts_disjoint_membership_states():
        club = ClubFactory.build(
            members=[MemberFactory.build(user_id=SOME_USER_ID)],
            banned_users=[PydanticObjectId("507f1f77bcf86cd799439012")],
            pending_approvals=[PendingApprovalSchema(user_id=PydanticObjectId("507f1f77bcf86cd799439013"))],
        )
        assert len(club.members) == 1
