from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import PasswordResetValidationContext
from canterlot.services import EmailDispatchService, UserService, VerificationService
from canterlot.types import NormalizedEmailStr, UsernameStr, VerificationScope
from canterlot.utils import get_logger

logger = get_logger(__name__)


class RequestPasswordResetUseCase:
    def __init__(
        self,
        user_service: UserService,
        verification_service: VerificationService,
        email_dispatch: EmailDispatchService,
    ):
        self.__user_service = user_service
        self.__verification_service = verification_service
        self.__email_dispatch = email_dispatch

    async def execute(self, identifier: NormalizedEmailStr | UsernameStr) -> None:
        log = logger.bind(identifier=str(identifier))
        log.info("Executing password reset request use case")

        # ---------------------------------------------------------
        # 1. Resolve User Record (Short-circuit on missing)
        # ---------------------------------------------------------
        user = await self.__user_service.find_by_identifier(identifier)
        if user is None or not user.id:
            log.info("Password reset request completed: no user matched identifier")
            return

        # ---------------------------------------------------------
        # 2. Issue Verification Code
        # ---------------------------------------------------------
        code = await self.__verification_service.create_code(
            user_id=user.id,
            scope=VerificationScope.PASSWORD_RESET,
        )

        # ---------------------------------------------------------
        # 3. Dispatch Validation Email
        # ---------------------------------------------------------
        context = PasswordResetValidationContext.from_domain(
            user=user,
            code=code,
            is_creation=user.hashed_password is None,
        )

        task = EmailTaskPayload(
            template=Templates.LUNA_PASSWORD_RESET,
            to=user.email,
            context=context,
        )

        await self.__email_dispatch.dispatch(
            task=task,
            prefs=user.email_preferences,
        )

        log.info("Password reset validation email dispatched successfully", user_id=str(user.id))
