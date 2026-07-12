from dataclasses import dataclass

from beanie import PydanticObjectId

from canterlot.dto.auth import ConnectedProvidersResponse, OAuthSignInResponse, TokenResponse, UserRegisterRequest
from canterlot.exceptions import (
    AuthProviderAlreadyLinkedError,
    AuthProviderNotLinkedError,
    EmailAlreadyExistsError,
    GatewayConfigurationError,
    InvalidCredentialsError,
    LastAuthenticationMethodError,
    OAuthAccountCreationConflictError,
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


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


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

        tokens = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, tokens.refresh_token)

        log.info("User registration transaction completed successfully")
        return RegisterResult(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            user_id=user_id,
        )

    async def login_user(self, username: UsernameStr, plain_password: str) -> TokenResponse:
        log = logger.bind(username=username)
        log.info("Attempting user authentication")

        user = await self.__user_repo.find_by_username(username)
        if not (user and user.id and user.hashed_password and verify_password(plain_password, user.hashed_password)):
            log.warn("Authentication failed: invalid security credentials", error_type="credentials_mismatch")
            raise InvalidCredentialsError("Incorrect username or password")

        user_id = user.id
        log = log.bind(user_id=str(user_id))

        tokens = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, tokens.refresh_token)

        log.info("User authenticated successfully, tokens issued")
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )

    async def rotate_refresh_token(self, user_id: PydanticObjectId, old_token: str) -> TokenResponse:
        log = logger.bind(user_id=str(user_id))
        log.info("Executing stateful refresh token rotation schema")

        await self.__user_repo.pull_refresh_token_by_id(user_id, old_token)

        tokens = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, tokens.refresh_token)

        log.info("Refresh token rotation completed successfully")
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )

    def __create_tokens(self, user_id: PydanticObjectId) -> TokenPair:
        return TokenPair(
            access_token=create_access_token(user_id),
            refresh_token=create_refresh_token(user_id),
        )

    def __get_oauth_provider(self, provider: AuthProviderName) -> OAuthProvider:
        try:
            return self.__oauth_providers[provider]
        except KeyError:
            logger.bind(provider=provider).warn("Requested authentication provider is not configured")
            raise GatewayConfigurationError(f"The '{provider}' authentication provider is not available.") from None

    async def __issue_login_tokens(self, user_id: PydanticObjectId, outcome: AuthOutcome) -> OAuthSignInResponse:
        tokens = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, tokens.refresh_token)

        return OAuthSignInResponse(
            outcome=outcome, access_token=tokens.access_token, refresh_token=tokens.refresh_token
        )

    async def sign_in_with_provider(self, provider: AuthProviderName, credential: str) -> OAuthSignInResponse:
        log = logger.bind(provider=provider)
        log.info("Attempting OAuth provider sign-in")

        identity = await self.__get_oauth_provider(provider).verify(credential)

        existing_id = await self.__user_repo.find_id_by_linked_provider(provider, identity.external_id)
        if existing_id:
            log.info("OAuth identity matched an existing linked account", user_id=str(existing_id))
            return await self.__issue_login_tokens(existing_id, AuthOutcome.LOGGED_IN)

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
        saved_user = await self.__user_repo.save_new_oauth_account(user)
        if saved_user is None:
            log.info("Lost a concurrent account-creation race for this identity, logging into the winning account")
            winner_id = await self.__user_repo.find_id_by_linked_provider(provider, identity.external_id)
            if winner_id is None:
                log.error("Account-creation conflict left no matching account behind")
                raise OAuthAccountCreationConflictError("Something went wrong signing you in; please try again.")
            return await self.__issue_login_tokens(winner_id, AuthOutcome.LOGGED_IN)

        log.info("New account created from OAuth identity", user_id=str(saved_user.id))
        return await self.__issue_login_tokens(PydanticObjectId(saved_user.id), AuthOutcome.CREATED)

    async def link_provider(self, user_id: PydanticObjectId, provider: AuthProviderName, credential: str) -> None:
        log = logger.bind(user_id=str(user_id), provider=provider)
        log.info("Attempting to link a new authentication provider")

        identity = await self.__get_oauth_provider(provider).verify(credential)

        existing_id = await self.__user_repo.find_id_by_linked_provider(provider, identity.external_id)
        if existing_id and existing_id != user_id:
            log.warn("Link rejected: credential already linked to a different account")
            raise AuthProviderAlreadyLinkedError(f"This {provider} account is already linked to a different user.")

        if existing_id:
            log.info("Provider already linked to this account, nothing to do")
            return

        linked = await self.__user_repo.add_linked_provider(
            user_id,
            LinkedProviderSchema(provider=provider, external_id=identity.external_id),
        )
        if not linked:
            log.warn("Link rejected: a concurrent request linked this credential to a different account first")
            raise AuthProviderAlreadyLinkedError(f"This {provider} account is already linked to a different user.")

        log.info("Authentication provider linked successfully")

    async def disconnect_provider(self, user_id: PydanticObjectId, provider: AuthProviderName) -> None:
        log = logger.bind(user_id=str(user_id), provider=provider)
        log.info("Attempting to disconnect an authentication provider")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warn("Disconnect aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        if not any(linked.provider == provider for linked in user.linked_providers):
            log.warn("Disconnect rejected: provider is not linked to this account")
            raise AuthProviderNotLinkedError(f"No linked '{provider}' account to disconnect.")

        remaining_providers = [linked for linked in user.linked_providers if linked.provider != provider]
        if not user.hashed_password and not remaining_providers:
            log.warn("Disconnect rejected: this is the account's last remaining authentication method")
            raise LastAuthenticationMethodError("Cannot disconnect your only remaining way to sign in.")

        await self.__user_repo.remove_linked_provider(user_id, provider)
        log.info("Authentication provider disconnected successfully")

    async def list_connected_providers(self, user_id: PydanticObjectId) -> ConnectedProvidersResponse:
        log = logger.bind(user_id=str(user_id))
        log.info("Fetching connected authentication providers")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warn("Lookup aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        return ConnectedProvidersResponse.from_model(user)
