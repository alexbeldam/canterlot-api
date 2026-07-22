from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from beanie import PydanticObjectId
from starlette.testclient import TestClient

from canterlot.app import create_app
from canterlot.emails.webhooks import ResendWebhookHandler
from canterlot.factories import UserFactory
from canterlot.gateways.auth.risc import GoogleRiscVerifier
from canterlot.models.user import UserModel
from canterlot.repositories import RateLimiter
from canterlot.routers.dependencies.providers import (
    RefreshTokenContext,
    get_accept_invite_use_case,
    get_approve_pending_member_use_case,
    get_auth_service,
    get_book_repository,
    get_book_service,
    get_cache_repository,
    get_catalog_service,
    get_change_member_role_use_case,
    get_change_password_use_case,
    get_club_repository,
    get_club_service,
    get_create_club_use_case,
    get_create_invite_use_case,
    get_create_password_use_case,
    get_create_session_use_case,
    get_current_user,
    get_current_user_id,
    get_disconnect_auth_provider_use_case,
    get_dissolve_club_use_case,
    get_email_dispatch_service,
    get_google_risc_verifier,
    get_health_service,
    get_invite_repository,
    get_invite_service,
    get_link_auth_provider_use_case,
    get_optional_refresh_token_context,
    get_rate_limiter,
    get_reclaim_club_ownership_use_case,
    get_register_user_use_case,
    get_remove_club_member_use_case,
    get_resend_webhook_handler,
    get_revoke_auth_provider_use_case,
    get_transfer_club_ownership_use_case,
    get_user_id_from_valid_refresh_token,
    get_user_id_from_valid_reset_token,
    get_user_repository,
    get_user_service,
    get_verification_repository,
    get_verification_service,
    get_verified_user,
    get_verified_user_id,
)
from canterlot.use_cases import (
    AcceptInviteUseCase,
    ApprovePendingMemberUseCase,
    ChangeMemberRoleUseCase,
    ChangePasswordUseCase,
    CreateClubUseCase,
    CreateInviteUseCase,
    CreatePasswordUseCase,
    CreateSessionUseCase,
    DisconnectAuthProviderUseCase,
    DissolveClubUseCase,
    LinkAuthProviderUseCase,
    ReclaimClubOwnershipUseCase,
    RegisterUserUseCase,
    RemoveClubMemberUseCase,
    RevokeAuthProviderUseCase,
    TransferClubOwnershipUseCase,
)

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439013")


# --- Gateway & Webhook Fixtures ---
@pytest.fixture
def google_risc_verifier() -> AsyncMock:
    return AsyncMock(spec=GoogleRiscVerifier)


@pytest.fixture
def resend_webhook_handler() -> AsyncMock:
    return AsyncMock(spec=ResendWebhookHandler)


# --- Use Case Fixtures ---
@pytest.fixture
def accept_invite_use_case() -> AsyncMock:
    return AsyncMock(spec=AcceptInviteUseCase)


@pytest.fixture
def approve_pending_member_use_case() -> AsyncMock:
    return AsyncMock(spec=ApprovePendingMemberUseCase)


@pytest.fixture
def change_member_role_use_case() -> AsyncMock:
    return AsyncMock(spec=ChangeMemberRoleUseCase)


@pytest.fixture
def change_password_use_case() -> AsyncMock:
    return AsyncMock(spec=ChangePasswordUseCase)


@pytest.fixture
def create_club_use_case() -> AsyncMock:
    return AsyncMock(spec=CreateClubUseCase)


@pytest.fixture
def create_invite_use_case() -> AsyncMock:
    return AsyncMock(spec=CreateInviteUseCase)


@pytest.fixture
def create_password_use_case() -> AsyncMock:
    return AsyncMock(spec=CreatePasswordUseCase)


@pytest.fixture
def create_session_use_case() -> AsyncMock:
    return AsyncMock(spec=CreateSessionUseCase)


@pytest.fixture
def disconnect_auth_provider_use_case() -> AsyncMock:
    return AsyncMock(spec=DisconnectAuthProviderUseCase)


@pytest.fixture
def dissolve_club_use_case() -> AsyncMock:
    return AsyncMock(spec=DissolveClubUseCase)


@pytest.fixture
def link_auth_provider_use_case() -> AsyncMock:
    return AsyncMock(spec=LinkAuthProviderUseCase)


@pytest.fixture
def reclaim_club_ownership_use_case() -> AsyncMock:
    return AsyncMock(spec=ReclaimClubOwnershipUseCase)


@pytest.fixture
def register_user_use_case() -> AsyncMock:
    return AsyncMock(spec=RegisterUserUseCase)


@pytest.fixture
def remove_club_member_use_case() -> AsyncMock:
    return AsyncMock(spec=RemoveClubMemberUseCase)


@pytest.fixture
def revoke_auth_provider_use_case() -> AsyncMock:
    return AsyncMock(spec=RevokeAuthProviderUseCase)


@pytest.fixture
def transfer_club_ownership_use_case() -> AsyncMock:
    return AsyncMock(spec=TransferClubOwnershipUseCase)


# --- Router Infrastructure Fixtures ---
@pytest.fixture
def rate_limiter() -> AsyncMock:
    mock = AsyncMock(spec=RateLimiter)
    mock.evaluate.return_value = 0
    return mock


@pytest.fixture
def current_user() -> UserModel:
    return UserFactory.build(
        id=SOME_USER_ID,
        accepted_terms_version=1,
        accepted_privacy_version=1,
        profile_completed_at=datetime.now(UTC),
    )


@pytest.fixture
def redis_pipeline() -> AsyncMock:
    pipeline_mock = AsyncMock()
    pipeline_mock.execute.return_value = (1, None)

    pipeline_mock.incr = Mock()
    pipeline_mock.expire = Mock()
    pipeline_mock.ttl = Mock()

    return pipeline_mock


@pytest.fixture
def redis_client(redis_pipeline: AsyncMock) -> AsyncMock:
    mock = AsyncMock()
    mock.incr.return_value = 1
    mock.ttl.return_value = -1

    pipeline_context = MagicMock()
    pipeline_context.__aenter__.return_value = redis_pipeline
    mock.pipeline = MagicMock(return_value=pipeline_context)

    return mock


@pytest.fixture
def client(  # noqa: PLR0917
    auth_service: AsyncMock,
    book_service: AsyncMock,
    catalog_service: AsyncMock,
    club_service: AsyncMock,
    invite_service: AsyncMock,
    user_service: AsyncMock,
    email_dispatch_service: AsyncMock,
    verification_service: AsyncMock,
    health_service: AsyncMock,
    accept_invite_use_case: AsyncMock,
    approve_pending_member_use_case: AsyncMock,
    change_member_role_use_case: AsyncMock,
    change_password_use_case: AsyncMock,
    create_club_use_case: AsyncMock,
    create_invite_use_case: AsyncMock,
    create_password_use_case: AsyncMock,
    create_session_use_case: AsyncMock,
    disconnect_auth_provider_use_case: AsyncMock,
    dissolve_club_use_case: AsyncMock,
    link_auth_provider_use_case: AsyncMock,
    reclaim_club_ownership_use_case: AsyncMock,
    register_user_use_case: AsyncMock,
    remove_club_member_use_case: AsyncMock,
    revoke_auth_provider_use_case: AsyncMock,
    transfer_club_ownership_use_case: AsyncMock,
    club_repo: AsyncMock,
    user_repo: AsyncMock,
    book_repo: AsyncMock,
    invite_repo: AsyncMock,
    cache_repo: AsyncMock,
    verification_repo: AsyncMock,
    rate_limiter: AsyncMock,
    current_user: UserModel,
    redis_client: AsyncMock,
    email_task_queue: AsyncMock,
    google_risc_verifier: AsyncMock,
    resend_webhook_handler: AsyncMock,
) -> Iterator[TestClient]:
    app = create_app()

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app.router.lifespan_context = _noop_lifespan
    app.state.redis_client = redis_client
    app.state.email_task_queue = email_task_queue

    # --- 1. Service Overrides ---
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_book_service] = lambda: book_service
    app.dependency_overrides[get_catalog_service] = lambda: catalog_service
    app.dependency_overrides[get_club_service] = lambda: club_service
    app.dependency_overrides[get_invite_service] = lambda: invite_service
    app.dependency_overrides[get_user_service] = lambda: user_service
    app.dependency_overrides[get_email_dispatch_service] = lambda: email_dispatch_service
    app.dependency_overrides[get_verification_service] = lambda: verification_service
    app.dependency_overrides[get_health_service] = lambda: health_service

    # --- 2. Use Case Overrides ---
    app.dependency_overrides[get_accept_invite_use_case] = lambda: accept_invite_use_case
    app.dependency_overrides[get_approve_pending_member_use_case] = lambda: approve_pending_member_use_case
    app.dependency_overrides[get_change_member_role_use_case] = lambda: change_member_role_use_case
    app.dependency_overrides[get_change_password_use_case] = lambda: change_password_use_case
    app.dependency_overrides[get_create_club_use_case] = lambda: create_club_use_case
    app.dependency_overrides[get_create_invite_use_case] = lambda: create_invite_use_case
    app.dependency_overrides[get_create_password_use_case] = lambda: create_password_use_case
    app.dependency_overrides[get_create_session_use_case] = lambda: create_session_use_case
    app.dependency_overrides[get_disconnect_auth_provider_use_case] = lambda: disconnect_auth_provider_use_case
    app.dependency_overrides[get_dissolve_club_use_case] = lambda: dissolve_club_use_case
    app.dependency_overrides[get_link_auth_provider_use_case] = lambda: link_auth_provider_use_case
    app.dependency_overrides[get_reclaim_club_ownership_use_case] = lambda: reclaim_club_ownership_use_case
    app.dependency_overrides[get_register_user_use_case] = lambda: register_user_use_case
    app.dependency_overrides[get_remove_club_member_use_case] = lambda: remove_club_member_use_case
    app.dependency_overrides[get_revoke_auth_provider_use_case] = lambda: revoke_auth_provider_use_case
    app.dependency_overrides[get_transfer_club_ownership_use_case] = lambda: transfer_club_ownership_use_case

    # --- 3. Repository & Infra Overrides ---
    app.dependency_overrides[get_club_repository] = lambda: club_repo
    app.dependency_overrides[get_user_repository] = lambda: user_repo
    app.dependency_overrides[get_book_repository] = lambda: book_repo
    app.dependency_overrides[get_invite_repository] = lambda: invite_repo
    app.dependency_overrides[get_cache_repository] = lambda: cache_repo
    app.dependency_overrides[get_verification_repository] = lambda: verification_repo
    app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter

    # --- 4. Webhook & Gateway Overrides ---
    app.dependency_overrides[get_google_risc_verifier] = lambda: google_risc_verifier
    app.dependency_overrides[get_resend_webhook_handler] = lambda: resend_webhook_handler

    # --- 5. Auth & User Resolution Overrides ---
    app.dependency_overrides[get_current_user_id] = lambda: SOME_USER_ID
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_verified_user_id] = lambda: SOME_USER_ID
    app.dependency_overrides[get_verified_user] = lambda: current_user

    app.dependency_overrides[get_user_id_from_valid_refresh_token] = lambda: RefreshTokenContext(
        user_id=SOME_USER_ID, token="old-refresh-token"
    )
    app.dependency_overrides[get_optional_refresh_token_context] = lambda: RefreshTokenContext(
        user_id=SOME_USER_ID, token="old-refresh-token"
    )
    app.dependency_overrides[get_user_id_from_valid_reset_token] = lambda: SOME_USER_ID

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
