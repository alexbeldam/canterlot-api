from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId
from pydantic import ValidationError

from canterlot.dto.club import ClubCreateRequest, ClubDetailResponse, ClubResponse, ClubSettingsUpdateRequest
from canterlot.models.club import ClubModel, MemberSchema, PendingApprovalSchema
from canterlot.models.enums import JoinPolicy, MemberRole

SOME_OWNER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_PENDING_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_OTHER_PENDING_ID = PydanticObjectId("507f1f77bcf86cd799439013")
SOME_ADMIN_ID = PydanticObjectId("507f1f77bcf86cd799439014")
SOME_MEMBER_ID = PydanticObjectId("507f1f77bcf86cd799439015")


def describe_club_create_request():
    def it_defaults_preferred_languages_to_an_empty_list():
        request = ClubCreateRequest(name="Book Club")
        assert request.preferred_languages == []

    def it_normalizes_preferred_languages():
        request = ClubCreateRequest(name="Book Club", preferred_languages=["English", "  pt-br  "])
        assert request.preferred_languages == ["en", "pt-BR"]


def describe_club_settings_update_request():
    def it_accepts_a_single_field():
        request = ClubSettingsUpdateRequest(allow_suggestions=False)
        assert request.allow_suggestions is False
        assert request.name is None

    def it_rejects_a_payload_with_no_fields_set():
        with pytest.raises(ValidationError):
            ClubSettingsUpdateRequest()

    def it_rejects_a_name_that_is_too_short():
        with pytest.raises(ValidationError):
            ClubSettingsUpdateRequest(name="ab")

    def it_rejects_an_invalid_join_policy():
        with pytest.raises(ValidationError):
            ClubSettingsUpdateRequest.model_validate({"join_policy": "NOT_A_POLICY"})

    def it_accepts_a_valid_join_policy():
        request = ClubSettingsUpdateRequest(join_policy=JoinPolicy.RESTRICTED)
        assert request.join_policy == JoinPolicy.RESTRICTED


def describe_club_response_from_model():
    def it_replaces_object_ids_with_usernames():
        club = ClubModel(
            name="Book Club",
            slug="book-club",
            members=[MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER)],
        )

        response = ClubResponse.from_model(club, user_usernames={SOME_OWNER_ID: "owner_1"})

        assert response.slug == "book-club"
        assert response.members[0].username == "owner_1"
        assert response.members[0].role == MemberRole.OWNER
        assert not hasattr(response, "id")
        assert not hasattr(response, "banned_users")
        assert not hasattr(response, "pending_approvals")
        assert not hasattr(response, "catalog")

    def it_sorts_members_by_role_then_by_username():
        club = ClubModel(
            name="Book Club",
            slug="book-club",
            members=[
                MemberSchema(user_id=SOME_MEMBER_ID, role=MemberRole.MEMBER),
                MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER),
                MemberSchema(user_id=SOME_OTHER_PENDING_ID, role=MemberRole.ADMIN),
                MemberSchema(user_id=SOME_ADMIN_ID, role=MemberRole.ADMIN),
            ],
        )
        usernames = {
            SOME_MEMBER_ID: "zoe",
            SOME_OWNER_ID: "owner_1",
            SOME_OTHER_PENDING_ID: "bob",
            SOME_ADMIN_ID: "alice",
        }

        response = ClubResponse.from_model(club, user_usernames=usernames)

        assert [(m.role, m.username) for m in response.members] == [
            (MemberRole.OWNER, "owner_1"),
            (MemberRole.ADMIN, "alice"),
            (MemberRole.ADMIN, "bob"),
            (MemberRole.MEMBER, "zoe"),
        ]


def describe_club_detail_response_from_model_with_pending():
    def it_resolves_pending_approvals_to_usernames_and_timestamps():
        club = ClubModel(
            name="Book Club",
            slug="book-club",
            members=[MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER)],
            pending_approvals=[PendingApprovalSchema(user_id=SOME_PENDING_ID)],
        )

        response = ClubDetailResponse.from_model_with_pending(
            club,
            user_usernames={SOME_OWNER_ID: "owner_1"},
            pending_usernames={SOME_PENDING_ID: "pending_1"},
        )

        assert response.members[0].username == "owner_1"
        assert response.pending_approvals[0].username == "pending_1"
        assert response.pending_approvals[0].requested_at == club.pending_approvals[0].requested_at

    def it_never_exposes_banned_users():
        club = ClubModel(name="Book Club", slug="book-club")

        response = ClubDetailResponse.from_model_with_pending(club, {}, {})

        assert not hasattr(response, "banned_users")
        assert response.pending_approvals == []

    def it_sorts_pending_approvals_by_requested_at_regardless_of_storage_order():
        now = datetime.now(UTC)
        club = ClubModel(
            name="Book Club",
            slug="book-club",
            members=[MemberSchema(user_id=SOME_OWNER_ID, role=MemberRole.OWNER)],
            pending_approvals=[
                PendingApprovalSchema(user_id=SOME_PENDING_ID, requested_at=now),
                PendingApprovalSchema(user_id=SOME_OTHER_PENDING_ID, requested_at=now - timedelta(days=1)),
            ],
        )

        response = ClubDetailResponse.from_model_with_pending(
            club,
            user_usernames={SOME_OWNER_ID: "owner_1"},
            pending_usernames={SOME_PENDING_ID: "pending_1", SOME_OTHER_PENDING_ID: "pending_2"},
        )

        assert [p.username for p in response.pending_approvals] == ["pending_2", "pending_1"]
