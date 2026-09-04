from canterlot.dto.auth import TokenResponse
from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import PasswordChangedContext
from canterlot.models import UserModel
from canterlot.services import AuthService, EmailDispatchService
from canterlot.types import PasswordStr
from canterlot.utils import get_logger

logger = get_logger(__name__)


class ResetPasswordUseCase:
    def __init__(
        self,
        auth_service: AuthService,
        email_dispatch: EmailDispatchService,
    ):
        self.__auth_service = auth_service
        self.__email_dispatch = email_dispatch

    async def execute(self, user: UserModel, new_password: PasswordStr) -> TokenResponse:
        log = logger.bind(user_id=str(user.id))
        log.info("Executing password reset execution use case")

        # ---------------------------------------------------------
        # 1. Set New Password & Rotate Single Active Session
        # ---------------------------------------------------------
        is_creation = user.hashed_password is None
        tokens = await self.__auth_service.set_password(
            user=user,
            password=new_password,
            is_reset=True,
        )

        # ---------------------------------------------------------
        # 2. Dispatch Confirmation Email
        # ---------------------------------------------------------
        context = PasswordChangedContext.from_domain(
            recipient=user,
            is_creation=is_creation,
        )

        task = EmailTaskPayload(
            template=Templates.LUNA_PASSWORD_CHANGED,
            to=user.email,
            context=context,
        )

        await self.__email_dispatch.dispatch(
            task=task,
            prefs=user.email_preferences,
        )

        log.info("Password reset executed and confirmation dispatched successfully")
        return tokens
