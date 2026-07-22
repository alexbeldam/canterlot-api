from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import LunaProviderActionContext
from canterlot.models.user import UserModel
from canterlot.services.auth import AuthService
from canterlot.services.dispatch import EmailDispatchService
from canterlot.types import AuthProviderName


class LinkAuthProviderUseCase:
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
        credential: str,
        redirect_uri: str | None = None,
    ) -> None:
        user_id = PydanticObjectId(user.id)

        # ---------------------------------------------------------
        # 1. Link Provider via AuthService
        # ---------------------------------------------------------
        await self.__auth_service.link_provider(
            user_id=user_id,
            provider=provider,
            credential=credential,
            redirect_uri=redirect_uri,
        )

        # ---------------------------------------------------------
        # 2. Dispatch Notification Email
        # ---------------------------------------------------------
        context = LunaProviderActionContext.from_domain(
            recipient=user,
            provider_name=provider,
        )

        task = EmailTaskPayload(
            template=Templates.LUNA_PROVIDER_LINKED,
            to=user.email,
            context=context,
        )

        await self.__email_dispatch.dispatch(task=task, prefs=user.email_preferences)
