from beanie import PydanticObjectId

from canterlot.dto.auth import TokenResponse, UserRegisterRequest
from canterlot.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    UsernameAlreadyExistsError,
)
from canterlot.models import UserModel
from canterlot.models.user import UsernameStr
from canterlot.repositories import UserRepository
from canterlot.utils import (
    create_access_token,
    create_refresh_token,
    get_logger,
    hash_password,
    verify_password,
)

logger = get_logger(__name__)


class RegisterResult(TokenResponse):
    user_id: PydanticObjectId


class AuthService:
    def __init__(self, user_repo: UserRepository):
        self.__user_repo = user_repo

    async def register_user(
        self,
        request: UserRegisterRequest,
        invited_by: UsernameStr | None = None,
    ) -> RegisterResult:
        log = logger.bind(username=request.username, email=request.email, invited_by=invited_by)
        log.info("Attempting user registration account creation")

        if await self.__user_repo.exists_by_username(request.username):
            log.warn("Registration rejected: username conflict", reason="username_taken")
            raise UsernameAlreadyExistsError(f"Username '{request.username}' is already taken.")

        if await self.__user_repo.exists_by_email(request.email):
            log.warn("Registration rejected: email conflict", reason="email_registered")
            raise EmailAlreadyExistsError(f"Email '{request.email}' is already registered.")

        user = UserModel(
            name=request.name,
            username=request.username,
            email=request.email,
            hashed_password=hash_password(request.password),
        )

        saved_user = await self.__user_repo.save(user)
        user_id = PydanticObjectId(saved_user.id)

        log = log.bind(user_id=str(user_id))

        if invited_by:
            log.info("Processing referral growth attribution")
            await self.__user_repo.increment_referral_count_by_username(invited_by)

        access_token, refresh_token = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, refresh_token)

        log.info("User registration transaction completed successfully")
        return RegisterResult(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user_id,
        )

    async def login_user(self, username: UsernameStr, plain_password: str) -> TokenResponse:
        log = logger.bind(username=username)
        log.info("Attempting user authentication")

        user = await self.__user_repo.find_by_username(username)
        if not (user and user.id and verify_password(plain_password, user.hashed_password)):
            log.warn("Authentication failed: invalid security credentials", error_type="credentials_mismatch")
            raise InvalidCredentialsError("Incorrect username or password")

        user_id = user.id
        log = log.bind(user_id=str(user_id))

        access_token, refresh_token = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, refresh_token)

        log.info("User authenticated successfully, tokens issued")
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def rotate_refresh_token(self, user_id: PydanticObjectId, old_token: str) -> TokenResponse:
        log = logger.bind(user_id=str(user_id))
        log.info("Executing stateful refresh token rotation schema")

        await self.__user_repo.pull_refresh_token_by_id(user_id, old_token)

        access_token, refresh_token = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, refresh_token)

        log.info("Refresh token rotation completed successfully")
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def __create_tokens(self, user_id: PydanticObjectId) -> tuple[str, str]:
        access_token = create_access_token(user_id)
        refresh_token = create_refresh_token(user_id)

        return access_token, refresh_token
