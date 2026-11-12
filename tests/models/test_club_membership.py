from beanie import PydanticObjectId

from canterlot.hoodie import link_id
from canterlot.types import MembershipStatus
from tools.factories import ClubMembershipFactory


def describe_club_membership_construction():
    def it_builds_with_a_status():
        membership = ClubMembershipFactory.build(status=MembershipStatus.OWNER)

        assert membership.status == MembershipStatus.OWNER
        assert isinstance(link_id(membership.club), PydanticObjectId)
        assert isinstance(link_id(membership.user), PydanticObjectId)

    def it_defaults_joined_at_and_requested_at_to_none():
        membership = ClubMembershipFactory.build(status=MembershipStatus.MEMBER)

        assert membership.joined_at is None
        assert membership.requested_at is None
