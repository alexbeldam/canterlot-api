import pytest
from beanie import PydanticObjectId
from pydantic import ValidationError

from canterlot.models.club import ClubCreateRequest, ClubModel, MemberSchema
from canterlot.models.enums import JoinPolicy

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def describe_club_name_constraints():
    @pytest.mark.parametrize("bad_name", ["ab", "a" * 51, "  "])
    def it_rejects_names_outside_the_length_bounds(bad_name: str):
        with pytest.raises(ValidationError):
            ClubModel(name=bad_name)

    def it_accepts_a_name_within_bounds():
        assert ClubModel(name="Book Club").name == "Book Club"


def describe_club_defaults():
    def it_applies_public_join_policy_and_allows_suggestions_by_default():
        club = ClubModel(name="Book Club")
        assert club.join_policy == JoinPolicy.PUBLIC
        assert club.allow_suggestions is True
        assert club.members == []
        assert club.catalog == []


def describe_membership_state_exclusivity():
    def it_rejects_a_user_who_is_both_an_active_member_and_banned():
        with pytest.raises(ValidationError, match="active members and banned"):
            ClubModel(
                name="Book Club",
                members=[MemberSchema(user_id=SOME_USER_ID)],
                banned_users=[SOME_USER_ID],
            )

    def it_rejects_a_user_who_is_both_an_active_member_and_pending():
        with pytest.raises(ValidationError, match="active members and pending"):
            ClubModel(
                name="Book Club",
                members=[MemberSchema(user_id=SOME_USER_ID)],
                pending_approvals=[SOME_USER_ID],
            )

    def it_rejects_a_user_who_is_both_banned_and_pending():
        with pytest.raises(ValidationError, match="banned and pending approval"):
            ClubModel(
                name="Book Club",
                banned_users=[SOME_USER_ID],
                pending_approvals=[SOME_USER_ID],
            )

    def it_accepts_disjoint_membership_states():
        club = ClubModel(
            name="Book Club",
            members=[MemberSchema(user_id=SOME_USER_ID)],
            banned_users=[PydanticObjectId("507f1f77bcf86cd799439012")],
            pending_approvals=[PydanticObjectId("507f1f77bcf86cd799439013")],
        )
        assert len(club.members) == 1


def describe_club_create_request():
    def it_defaults_preferred_languages_to_an_empty_list():
        request = ClubCreateRequest(name="Book Club")
        assert request.preferred_languages == []

    def it_normalizes_preferred_languages():
        request = ClubCreateRequest(name="Book Club", preferred_languages=["English", "  pt-br  "])
        assert request.preferred_languages == ["en", "pt-BR"]
