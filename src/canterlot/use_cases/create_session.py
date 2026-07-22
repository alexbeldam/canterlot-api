from dataclasses import dataclass
from typing import cast

from pydantic import SecretStr

from canterlot.dto.auth import CreateSessionRequest
from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import AuthProviderContext
from canterlot.exceptions import (
    ClubNotFoundError,
    InvalidInviteTokenError,
    InviteLinkDeactivatedError,
)
from canterlot.services.auth import AuthService
from canterlot.services.dispatch import EmailDispatchService
from canterlot.services.invite import InviteService
from canterlot.types import AuthOutcome, AuthProviderName, SessionType, UsernameStr
from canterlot.utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CreateSessionResult:
    access_token: str
    refresh_token: str
    is_new_user: bool = False
    location_header: str | None = None


class CreateSessionUseCase:
    def __init__(
        self,
        auth_service: AuthService,
        invite_service: InviteService,
        email_dispatch: EmailDispatchService,
    ):
        self.__auth_service = auth_service
        self.__invite_service = invite_service
        self.__email_dispatch = email_dispatch

    async def execute(self, payload: CreateSessionRequest) -> CreateSessionResult:
        # ---------------------------------------------------------
        # 1. Password Authentication
        # ---------------------------------------------------------
        if payload.type is SessionType.PASSWORD:
            login_result = await self.__auth_service.login_user(
                username=cast(UsernameStr, payload.username),
                plain_password=cast(SecretStr, payload.password),
            )
            return CreateSessionResult(
                access_token=login_result.access_token,
                refresh_token=login_result.refresh_token,
            )

        # ---------------------------------------------------------
        # 2. OAuth Authentication
        # ---------------------------------------------------------
        provider_name = cast(AuthProviderName, payload.provider)
        oauth_result = await self.__auth_service.sign_in_with_provider(
            provider_name,
            cast(str, payload.credential),
        )

        is_new_user = oauth_result.outcome == AuthOutcome.CREATED
        location_header = "/v1/users/me" if is_new_user else None

        if is_new_user:
            # ---------------------------------------------------------
            # 2a. Attribute Referral (if invite_id present)
            # ---------------------------------------------------------
            if payload.invite_id:
                await self._attribute_oauth_referral(payload.invite_id, payload.invited_by)

            # ---------------------------------------------------------
            # 2b. Dispatch OAuth Welcome Email
            # ---------------------------------------------------------
            if oauth_result.user:
                context = AuthProviderContext.from_domain(
                    recipient=oauth_result.user,
                    provider_name=provider_name,
                )

                task = EmailTaskPayload(
                    template=Templates.CELESTIA_OAUTH_WELCOME,
                    to=oauth_result.user.email,
                    context=context,
                )

                await self.__email_dispatch.dispatch(task=task, prefs=oauth_result.user.email_preferences)

        return CreateSessionResult(
            access_token=oauth_result.access_token,
            refresh_token=oauth_result.refresh_token,
            is_new_user=is_new_user,
            location_header=location_header,
        )

    async def _attribute_oauth_referral(
        self,
        invite_id: str,
        invited_by: UsernameStr | None,
    ) -> None:
        log = logger.bind(invite_id=invite_id)
        try:
            preview = await self.__invite_service.get_preview_metadata(invite_id, invited_by=invited_by)
        except (InvalidInviteTokenError, InviteLinkDeactivatedError, ClubNotFoundError):
            log.warning("Skipping referral attribution: invite could not be resolved for this new account")
            return

        if preview.invited_by_username:
            await self.__auth_service.attribute_referral(preview.invited_by_username)
