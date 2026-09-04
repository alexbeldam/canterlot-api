from beanie import PydanticObjectId

from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import EmailVerificationContext
from canterlot.exceptions.user import EmailAlreadyVerifiedError
from canterlot.models.user import UserModel
from canterlot.services import EmailDispatchService, VerificationService
from canterlot.types import VerificationScope
from canterlot.utils import get_logger

logger = get_logger(__name__)


class RequestEmailVerificationUseCase:
    def __init__(
        self,
        verification_service: VerificationService,
        email_dispatch: EmailDispatchService,
    ) -> None:
        self.__verification_service = verification_service
        self.__email_dispatch = email_dispatch

    async def execute(self, user: UserModel) -> None:
        log = logger.bind(user_id=str(user.id), email=user.email)
        log.info("Executing email verification request use case")

        # ---------------------------------------------------------
        # 1. Validate Verification Status
        # ---------------------------------------------------------
        if user.email_preferences.verified_at is not None:
            log.info("Email verification request aborted: user already verified")
            raise EmailAlreadyVerifiedError("Your email address is already verified.")

        # ---------------------------------------------------------
        # 2. Issue Verification Code
        # ---------------------------------------------------------
        code = await self.__verification_service.create_code(
            user_id=PydanticObjectId(user.id),
            scope=VerificationScope.EMAIL,
        )

        # ---------------------------------------------------------
        # 3. Dispatch Verification Email
        # ---------------------------------------------------------
        context = EmailVerificationContext.from_domain(
            recipient=user,
            code=code,
        )

        task = EmailTaskPayload(
            template=Templates.CELESTIA_VERIFY_EMAIL,
            to=user.email,
            context=context,
        )

        await self.__email_dispatch.dispatch(
            task=task,
            prefs=user.email_preferences,
        )

        log.info("Email verification email dispatched successfully")
