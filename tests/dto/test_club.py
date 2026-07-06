from beanie import PydanticObjectId

from canterlot.dto.club import ClubCreateRequest, ClubResponse
from canterlot.models.club import ClubModel, MemberSchema
from canterlot.models.enums import UserRole

SOME_OWNER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


def describe_club_create_request():
    def it_defaults_preferred_languages_to_an_empty_list():
        request = ClubCreateRequest(name="Book Club")
        assert request.preferred_languages == []

    def it_normalizes_preferred_languages():
        request = ClubCreateRequest(name="Book Club", preferred_languages=["English", "  pt-br  "])
        assert request.preferred_languages == ["en", "pt-BR"]


def describe_club_response_from_model():
    def it_replaces_object_ids_with_usernames():
        club = ClubModel(
            name="Book Club",
            slug="book-club",
            members=[MemberSchema(user_id=SOME_OWNER_ID, role=UserRole.OWNER)],
        )

        response = ClubResponse.from_model(club, user_usernames={SOME_OWNER_ID: "owner_1"})

        assert response.slug == "book-club"
        assert response.members[0].username == "owner_1"
        assert response.members[0].role == UserRole.OWNER
        assert not hasattr(response, "id")
        assert not hasattr(response, "banned_users")
        assert not hasattr(response, "pending_approvals")
        assert not hasattr(response, "catalog")
