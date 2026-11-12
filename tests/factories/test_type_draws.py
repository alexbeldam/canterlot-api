import pytest

from canterlot.types import ExtensionType, InviteType, SessionType
from tools.factories import (
    CreateInviteRequestFactory,
    CreateSessionRequestFactory,
    InviteFactory,
    LinkCadidateFactory,
)

BUILDS = 300


def describe_invite_factory():
    def it_builds_internally_consistent_invites_when_the_type_is_unpinned():
        invites = [InviteFactory.build() for _ in range(BUILDS)]

        assert {invite.type for invite in invites} == set(InviteType)
        for invite in invites:
            if invite.type is InviteType.PUBLIC:
                assert invite.target_email is None
                assert invite.target_user is None
                assert invite.created_by is None
                assert invite.expires_at is None
            else:
                assert invite.created_by is not None
                assert invite.expires_at is not None
                assert (invite.target_email is None) != (invite.target_user is None)

    @pytest.mark.parametrize("invite_type", list(InviteType))
    def it_builds_internally_consistent_invites_when_the_type_is_pinned(invite_type: InviteType):
        invites = [InviteFactory.build(type=invite_type) for _ in range(BUILDS)]

        assert {invite.type for invite in invites} == {invite_type}
        for invite in invites:
            if invite_type is InviteType.PUBLIC:
                assert invite.created_by is None
                assert invite.expires_at is None
            else:
                assert invite.created_by is not None
                assert (invite.target_email is None) != (invite.target_user is None)


def describe_create_invite_request_factory():
    def it_builds_valid_requests_when_the_type_is_unpinned():
        requests = [CreateInviteRequestFactory.build() for _ in range(BUILDS)]

        assert {request.type for request in requests} == set(InviteType)

    @pytest.mark.parametrize("invite_type", list(InviteType))
    def it_builds_valid_requests_when_the_type_is_pinned(invite_type: InviteType):
        requests = [CreateInviteRequestFactory.build(type=invite_type) for _ in range(BUILDS)]

        assert {request.type for request in requests} == {invite_type}


def describe_create_session_request_factory():
    def it_builds_valid_requests_when_the_type_is_unpinned():
        requests = [CreateSessionRequestFactory.build() for _ in range(BUILDS)]

        assert {request.type for request in requests} == set(SessionType)

    @pytest.mark.parametrize("session_type", list(SessionType))
    def it_builds_valid_requests_when_the_type_is_pinned(session_type: SessionType):
        requests = [CreateSessionRequestFactory.build(type=session_type) for _ in range(BUILDS)]

        assert {request.type for request in requests} == {session_type}


def describe_link_candidate_factory():
    def it_builds_a_url_whose_extension_matches_the_model_extension_when_unpinned():
        candidates = [LinkCadidateFactory.build() for _ in range(BUILDS)]

        assert {candidate.extension for candidate in candidates} == set(ExtensionType)
        for candidate in candidates:
            assert str(candidate.url).endswith(f".{candidate.extension.value}")

    @pytest.mark.parametrize("extension", list(ExtensionType))
    def it_builds_a_url_whose_extension_matches_the_model_extension_when_pinned(extension: ExtensionType):
        candidates = [LinkCadidateFactory.build(extension=extension) for _ in range(BUILDS)]

        assert all(str(candidate.url).endswith(f".{extension.value}") for candidate in candidates)
