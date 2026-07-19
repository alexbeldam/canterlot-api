import pytest
from beanie import PydanticObjectId
from pydantic import ValidationError

from canterlot.models.club import ClubModel, MemberSchema, PendingApprovalSchema
from canterlot.types import JoinPolicy

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def describe_club_name_constraints():
    @pytest.mark.parametrize("bad_name", ["ab", "a" * 51, "  "])
    def it_rejects_names_outside_the_length_bounds(bad_name: str):
        with pytest.raises(ValidationError):
            ClubModel(name=bad_name, slug="book-club")

    def it_accepts_a_name_within_bounds():
        assert ClubModel(name="Book Club", slug="book-club").name == "Book Club"


def describe_club_defaults():
    def it_applies_public_join_policy_and_allows_suggestions_by_default():
        club = ClubModel(name="Book Club", slug="book-club")
        assert club.join_policy == JoinPolicy.PUBLIC
        assert club.allow_suggestions is True
        assert club.members == []
        assert club.catalog == []
        assert club.ownership_transferred_at is None
        assert club.protected_former_owner_id is None


def describe_membership_state_exclusivity():
    def it_rejects_a_user_who_is_both_an_active_member_and_banned():
        with pytest.raises(ValidationError, match="active members and banned"):
            ClubModel(
                name="Book Club",
                slug="book-club",
                members=[MemberSchema(user_id=SOME_USER_ID)],
                banned_users=[SOME_USER_ID],
            )

    def it_rejects_a_user_who_is_both_an_active_member_and_pending():
        with pytest.raises(ValidationError, match="active members and pending"):
            ClubModel(
                name="Book Club",
                slug="book-club",
                members=[MemberSchema(user_id=SOME_USER_ID)],
                pending_approvals=[PendingApprovalSchema(user_id=SOME_USER_ID)],
            )

    def it_rejects_a_user_who_is_both_banned_and_pending():
        with pytest.raises(ValidationError, match="banned and pending approval"):
            ClubModel(
                name="Book Club",
                slug="book-club",
                banned_users=[SOME_USER_ID],
                pending_approvals=[PendingApprovalSchema(user_id=SOME_USER_ID)],
            )

    def it_accepts_disjoint_membership_states():
        club = ClubModel(
            name="Book Club",
            slug="book-club",
            members=[MemberSchema(user_id=SOME_USER_ID)],
            banned_users=[PydanticObjectId("507f1f77bcf86cd799439012")],
            pending_approvals=[PendingApprovalSchema(user_id=PydanticObjectId("507f1f77bcf86cd799439013"))],
        )
        assert len(club.members) == 1
