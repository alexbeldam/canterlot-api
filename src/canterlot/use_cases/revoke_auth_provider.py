from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import LunaProviderActionContext
from canterlot.services.auth import AuthService
from canterlot.services.dispatch import EmailDispatchService
from canterlot.types import AuthProviderName


class RevokeAuthProviderUseCase:
    def __init__(
        self,
        auth_service: AuthService,
        email_dispatch: EmailDispatchService,
    ):
        self.__auth_service = auth_service
        self.__email_dispatch = email_dispatch

    async def execute(
        self,
        provider: AuthProviderName,
        external_id: str,
    ) -> None:
        # ---------------------------------------------------------
        # 1. Execute Revocation in AuthService
        # ---------------------------------------------------------
        result = await self.__auth_service.revoke_provider_link(
            provider=provider,
            external_id=external_id,
        )

        # ---------------------------------------------------------
        # 2. Dispatch LUNA_LOCKED_OUT if user is locked out
        # ---------------------------------------------------------
        if result.user and result.is_locked_out:
            context = LunaProviderActionContext.from_domain(
                recipient=result.user,
                provider_name=provider,
            )

            task = EmailTaskPayload(
                template=Templates.LUNA_LOCKED_OUT,
                to=result.user.email,
                context=context,
            )

            await self.__email_dispatch.dispatch(
                task=task,
                prefs=result.user.email_preferences,
            )
