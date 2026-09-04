from dataclasses import dataclass

from beanie import PydanticObjectId

from canterlot.dto.auth import RegisterResponse, UserRegisterRequest
from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import EmailVerificationContext
from canterlot.services.auth import AuthService
from canterlot.services.club import ClubService
from canterlot.services.dispatch import EmailDispatchService
from canterlot.services.invite import InviteService
from canterlot.services.verification import VerificationService
from canterlot.types import ClubOnboardingStatus, VerificationScope


@dataclass(frozen=True, slots=True)
class RegisterUserUseCaseResult:
    response: RegisterResponse
    refresh_token: str


class RegisterUserUseCase:
    def __init__(
        self,
        auth_service: AuthService,
        invite_service: InviteService,
        club_service: ClubService,
        verification_service: VerificationService,
        email_dispatch: EmailDispatchService,
    ):
        self.__auth_service = auth_service
        self.__invite_service = invite_service
        self.__club_service = club_service
        self.__verification_service = verification_service
        self.__email_dispatch = email_dispatch

    async def execute(self, payload: UserRegisterRequest) -> RegisterUserUseCaseResult:
        validated_invite = None
        inviter_username = payload.invited_by

        # ---------------------------------------------------------
        # 1. Validate Invite (if provided)
        # ---------------------------------------------------------
        if payload.invite_id:
            validated_invite = await self.__invite_service.validate_incoming_invite(
                payload.invite_id,
                payload.email,
                payload.invited_by,
            )
            inviter_username = validated_invite.invited_by or payload.invited_by

        # ---------------------------------------------------------
        # 2. Register Account
        # ---------------------------------------------------------
        register_result = await self.__auth_service.register_user(payload, inviter_username)
        user = register_result.user
        uid = PydanticObjectId(user.id)

        onboarding = None

        # ---------------------------------------------------------
        # 3. Admit to Club & Record Invite Usage
        # ---------------------------------------------------------
        if validated_invite:
            onboarding = await self.__club_service.admit_user(
                validated_invite.club_id,
                uid,
                validated_invite.is_direct,
            )

            if (
                onboarding
                and onboarding.status in [ClubOnboardingStatus.JOINED, ClubOnboardingStatus.PENDING_APPROVAL]
                and payload.invite_id
            ):
                await self.__invite_service.register_invite_usage(payload.invite_id)

        # ---------------------------------------------------------
        # 4. Generate & Dispatch Verification Email
        # ---------------------------------------------------------
        code = await self.__verification_service.create_code(
            user_id=uid,
            scope=VerificationScope.EMAIL,
        )

        context = EmailVerificationContext.from_domain(
            recipient=user,
            code=code,
        )

        task = EmailTaskPayload(
            template=Templates.CELESTIA_VERIFY_EMAIL,
            to=user.email,
            context=context,
        )

        await self.__email_dispatch.dispatch(task=task, prefs=user.email_preferences)

        response_dto = RegisterResponse(
            access_token=register_result.access_token,
            token_type=register_result.token_type,
            onboarding=onboarding,
        )

        return RegisterUserUseCaseResult(
            response=response_dto,
            refresh_token=register_result.refresh_token,
        )
