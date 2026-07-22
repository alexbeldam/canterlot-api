from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.dto.club import ClubResponse
from canterlot.factories import ClubCreateRequestFactory, ClubFactory
from canterlot.models.club import MemberSchema
from canterlot.types import JoinPolicy, MemberRole
from canterlot.use_cases.create_club import CreateClubUseCase

CREATOR_ID = PydanticObjectId("507f1f77bcf86cd799439011")
CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")


@pytest.fixture
def use_case(
    club_service: AsyncMock,
    invite_service: AsyncMock,
) -> CreateClubUseCase:
    return CreateClubUseCase(
        club_service=club_service,
        invite_service=invite_service,
    )


def describe_create_club_use_case():
    async def it_creates_a_new_club_rotates_public_link_and_returns_club_response(
        use_case: CreateClubUseCase,
        club_service: AsyncMock,
        invite_service: AsyncMock,
    ):
        payload = ClubCreateRequestFactory.build(
            name="The Canterlot Archives",
            description="A cozy corner for reading literature.",
            join_policy=JoinPolicy.PUBLIC,
        )

        club = ClubFactory.build(
            id=CLUB_ID,
            name="The Canterlot Archives",
            slug="the-canterlot-archives",
            members=[MemberSchema(user_id=CREATOR_ID, role=MemberRole.OWNER)],
        )
        club_service.create_new_club.return_value = club
        club_service.resolve_member_usernames.return_value = {CREATOR_ID: "celestia"}
        invite_service.rotate_public_link.return_value = "public-token-123"

        response = await use_case.execute(creator_id=CREATOR_ID, payload=payload)

        assert isinstance(response, ClubResponse)
        assert response.name == "The Canterlot Archives"
        assert response.slug == "the-canterlot-archives"
        assert len(response.members) == 1
        assert response.members[0].username == "celestia"
        assert response.members[0].role == MemberRole.OWNER

        club_service.create_new_club.assert_awaited_once_with(
            creator_id=CREATOR_ID,
            data=payload,
        )
        invite_service.rotate_public_link.assert_awaited_once_with(
            club_id=CLUB_ID,
            user_id=CREATOR_ID,
        )
        club_service.resolve_member_usernames.assert_awaited_once_with(club.members)
