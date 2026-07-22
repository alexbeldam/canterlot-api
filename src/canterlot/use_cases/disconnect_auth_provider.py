from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import AuthProviderContext
from canterlot.models.user import UserModel
from canterlot.services.auth import AuthService
from canterlot.services.dispatch import EmailDispatchService
from canterlot.types import AuthProviderName


class DisconnectAuthProviderUseCase:
    def __init__(
        self,
        auth_service: AuthService,
        email_dispatch: EmailDispatchService,
    ):
        self.__auth_service = auth_service
        self.__email_dispatch = email_dispatch

    async def execute(
        self,
        user: UserModel,
        provider: AuthProviderName,
    ) -> None:
        # ---------------------------------------------------------
        # 1. Disconnect Provider via AuthService
        # ---------------------------------------------------------
        await self.__auth_service.disconnect_provider(
            user=user,
            provider=provider,
        )

        # ---------------------------------------------------------
        # 2. Dispatch Notification Email
        # ---------------------------------------------------------
        context = AuthProviderContext.from_domain(
            recipient=user,
            provider_name=provider,
        )

        task = EmailTaskPayload(
            template=Templates.LUNA_PROVIDER_DISCONNECTED,
            to=user.email,
            context=context,
        )

        await self.__email_dispatch.dispatch(task=task, prefs=user.email_preferences)
