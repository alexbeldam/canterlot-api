from canterlot.types import InviteType, JoinPolicy
from tools.factories import InvitePreviewResponseFactory


def describe_invite_preview_response():
    def it_allows_an_absent_invited_by_username():
        preview = InvitePreviewResponseFactory.build(
            club_slug="book-club",
            club_name="Book Club",
            join_policy=JoinPolicy.PUBLIC,
            invite_type=InviteType.DIRECT,
            invited_by_username=None,
        )
        assert preview.invited_by_username is None
