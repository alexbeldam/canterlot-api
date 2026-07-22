from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from beanie import PydanticObjectId

from canterlot.dto.invite import InviteTokenResponse
from canterlot.emails.core.definitions import EmailTaskPayload
from canterlot.emails.core.schemas import InviteExternalContext, InviteInternalContext
from canterlot.factories import ClubFactory, CreateInviteRequestFactory, UserFactory
from canterlot.types import InviteType
from canterlot.use_cases.create_invite import CreateInviteUseCase

SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")
SOME_ISSUER_ID = PydanticObjectId("507f1f77bcf86cd799439011")


@pytest.fixture
def use_case(
    invite_service: AsyncMock,
    user_service: AsyncMock,
    email_dispatch_service: AsyncMock,
) -> CreateInviteUseCase:
    return CreateInviteUseCase(
        invite_service=invite_service,
        user_service=user_service,
        email_dispatch=email_dispatch_service,
    )


def describe_create_invite_use_case():
    async def it_rotates_public_link_without_dispatching_email(
        use_case: CreateInviteUseCase,
        invite_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        club = ClubFactory.build(id=SOME_CLUB_ID)
        issuer = UserFactory.build(id=SOME_ISSUER_ID)
        payload = CreateInviteRequestFactory.build(type=InviteType.PUBLIC)
        invite_service.rotate_public_link.return_value = "public-token-123"

        response = await use_case.execute(club, issuer, payload)

        assert isinstance(response, InviteTokenResponse)
        assert response.invite_token == "public-token-123"
        invite_service.rotate_public_link.assert_awaited_once_with(
            club_id=club.id,
            user_id=issuer.id,
        )
        email_dispatch_service.dispatch.assert_not_called()

    async def it_creates_external_invite_and_dispatches_external_email(
        use_case: CreateInviteUseCase,
        invite_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        club = ClubFactory.build(id=SOME_CLUB_ID)
        issuer = UserFactory.build(id=SOME_ISSUER_ID)
        payload = CreateInviteRequestFactory.build(type=InviteType.DIRECT, email="newbie@example.com")
        invite_service.create_external_invite.return_value = "external-token-456"

        mock_context = MagicMock(spec=InviteExternalContext)

        with patch(
            "canterlot.use_cases.create_invite.InviteExternalContext.from_domain",
            return_value=mock_context,
        ) as mock_from_domain:
            response = await use_case.execute(club, issuer, payload)

            assert response.invite_token == "external-token-456"
            invite_service.create_external_invite.assert_awaited_once_with(
                club_id=club.id,
                issuer_id=issuer.id,
                target_email="newbie@example.com",
            )
            mock_from_domain.assert_called_once_with(
                inviter=issuer,
                club=club,
                invite="external-token-456",
            )

            email_dispatch_service.dispatch.assert_awaited_once()
            task_arg = email_dispatch_service.dispatch.call_args.kwargs["task"]
            assert isinstance(task_arg, EmailTaskPayload)
            assert task_arg.to == "newbie@example.com"
            assert task_arg.context == mock_context

    async def it_creates_internal_invite_and_dispatches_internal_email_with_preferences(
        use_case: CreateInviteUseCase,
        invite_service: AsyncMock,
        user_service: AsyncMock,
        email_dispatch_service: AsyncMock,
    ):
        club = ClubFactory.build(id=SOME_CLUB_ID)
        issuer = UserFactory.build(id=SOME_ISSUER_ID)
        target_user = UserFactory.build(
            id=PydanticObjectId("507f1f77bcf86cd799439099"),
            username="twilight",
            email="twilight@example.com",
        )
        payload = CreateInviteRequestFactory.build(type=InviteType.DIRECT, username="twilight")

        user_service.get_by_username.return_value = target_user
        invite_service.create_internal_invite.return_value = "internal-token-789"

        mock_context = MagicMock(spec=InviteInternalContext)

        with patch(
            "canterlot.use_cases.create_invite.InviteInternalContext.from_domain",
            return_value=mock_context,
        ) as mock_from_domain:
            response = await use_case.execute(club, issuer, payload)

            assert response.invite_token == "internal-token-789"
            user_service.get_by_username.assert_awaited_once_with("twilight")
            invite_service.create_internal_invite.assert_awaited_once_with(
                club_id=club.id,
                issuer_id=issuer.id,
                target_user_id=target_user.id,
            )
            mock_from_domain.assert_called_once_with(
                recipient=target_user,
                inviter=issuer,
                club=club,
                invite="internal-token-789",
            )

            email_dispatch_service.dispatch.assert_awaited_once()
            call_kwargs = email_dispatch_service.dispatch.call_args.kwargs
            task_arg = call_kwargs["task"]
            assert isinstance(task_arg, EmailTaskPayload)
            assert task_arg.to == "twilight@example.com"
            assert task_arg.context == mock_context
            assert call_kwargs["prefs"] == target_user.email_preferences
