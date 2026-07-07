from beanie import PydanticObjectId

from canterlot.dto.auth import OAuthSignInResponse, TokenResponse, UserRegisterRequest
from canterlot.exceptions import (
    EmailAlreadyExistsError,
    GatewayConfigurationError,
    InvalidCredentialsError,
    UsernameAlreadyExistsError,
)
from canterlot.models import AuthOutcome, AuthProviderName, LinkedProviderSchema, UserModel
from canterlot.models.user import UsernameStr
from canterlot.providers.auth import OAuthProvider
from canterlot.repositories import UserRepository
from canterlot.utils import (
    create_access_token,
    create_refresh_token,
    get_logger,
    hash_password,
    make_username,
    verify_password,
)

logger = get_logger(__name__)


class RegisterResult(TokenResponse):
    user_id: PydanticObjectId


class AuthService:
    def __init__(self, user_repo: UserRepository, oauth_providers: dict[AuthProviderName, OAuthProvider]):
        self.__user_repo = user_repo
        self.__oauth_providers = oauth_providers

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
        if not (
            user and user.id and user.hashed_password and verify_password(plain_password, user.hashed_password)
        ):
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

    def __get_oauth_provider(self, provider: AuthProviderName) -> OAuthProvider:
        try:
            return self.__oauth_providers[provider]
        except KeyError:
            raise GatewayConfigurationError(f"The '{provider}' authentication provider is not available.") from None

    async def __issue_login_tokens(self, user_id: PydanticObjectId, outcome: AuthOutcome) -> OAuthSignInResponse:
        access_token, refresh_token = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, refresh_token)

        return OAuthSignInResponse(outcome=outcome, access_token=access_token, refresh_token=refresh_token)

    async def sign_in_with_provider(self, provider: AuthProviderName, credential: str) -> OAuthSignInResponse:
        log = logger.bind(provider=provider)
        log.info("Attempting OAuth provider sign-in")

        identity = await self.__get_oauth_provider(provider).verify(credential)

        existing = await self.__user_repo.find_by_linked_provider(provider, identity.external_id)
        if existing:
            log.info("OAuth identity matched an existing linked account", user_id=str(existing.id))
            return await self.__issue_login_tokens(PydanticObjectId(existing.id), AuthOutcome.LOGGED_IN)

        if await self.__user_repo.find_by_email(identity.email):
            log.info("OAuth identity's email matches an existing account with a different auth method")
            return OAuthSignInResponse(outcome=AuthOutcome.LINK_REQUIRED)

        username_seed = identity.name or identity.email.split("@")[0]
        username = await make_username(username_seed, self.__user_repo.exists_by_username)
        user = UserModel(
            name=identity.name or username,
            username=username,
            email=identity.email,
            linked_providers=[LinkedProviderSchema(provider=provider, external_id=identity.external_id)],
        )
        saved_user = await self.__user_repo.save(user)

        log.info("New account created from OAuth identity", user_id=str(saved_user.id))
        return await self.__issue_login_tokens(PydanticObjectId(saved_user.id), AuthOutcome.CREATED)
