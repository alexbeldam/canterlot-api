from canterlot.dto.invite import InvitePreviewResponse
from canterlot.models.enums import InviteType, JoinPolicy


def describe_invite_preview_response():
    def it_allows_an_absent_invited_by_username():
        preview = InvitePreviewResponse(
            club_slug="book-club",
            club_name="Book Club",
            join_policy=JoinPolicy.PUBLIC,
            invite_type=InviteType.DIRECT,
        )
        assert preview.invited_by_username is None
