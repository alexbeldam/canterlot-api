from dataclasses import dataclass

from pydantic import SecretStr

from canterlot.dto.auth import AccessTokenResponse
from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import PasswordChangedContext
from canterlot.models.user import UserModel
from canterlot.services.auth import AuthService
from canterlot.services.dispatch import EmailDispatchService
from canterlot.types import PasswordStr


@dataclass(frozen=True, slots=True)
class ChangePasswordUseCaseResult:
    response: AccessTokenResponse
    refresh_token: str


class ChangePasswordUseCase:
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
        current_password: SecretStr,
        new_password: PasswordStr,
    ) -> ChangePasswordUseCaseResult:
        # ---------------------------------------------------------
        # 1. Update Password & Issue New Tokens
        # ---------------------------------------------------------
        token_res = await self.__auth_service.change_password(
            user=user,
            current_password=current_password,
            new_password=new_password,
        )

        # ---------------------------------------------------------
        # 2. Dispatch Security Email
        # ---------------------------------------------------------
        context = PasswordChangedContext.from_domain(
            recipient=user,
            is_creation=False,
        )

        task = EmailTaskPayload(
            template=Templates.LUNA_PASSWORD_CHANGED,
            to=user.email,
            context=context,
        )

        await self.__email_dispatch.dispatch(task=task, prefs=user.email_preferences)

        return ChangePasswordUseCaseResult(
            response=AccessTokenResponse(
                access_token=token_res.access_token,
                token_type=token_res.token_type,
            ),
            refresh_token=token_res.refresh_token,
        )
