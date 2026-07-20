from dataclasses import dataclass
from datetime import UTC, datetime

from beanie import PydanticObjectId
from pydantic import BaseModel, HttpUrl

from canterlot.config import get_settings
from canterlot.dto.auth import ConnectedProvidersResponse, TokenResponse, UserRegisterRequest
from canterlot.exceptions import (
    AuthProviderAlreadyLinkedError,
    AuthProviderNotLinkedError,
    EmailAlreadyExistsError,
    GatewayConfigurationError,
    IncorrectPasswordError,
    InvalidCredentialsError,
    LastAuthenticationMethodError,
    OAuthAccountCreationConflictError,
    OAuthLinkRequiredError,
    StaleLegalVersionError,
    UsernameAlreadyExistsError,
)
from canterlot.gateways.auth import OAuthProvider
from canterlot.gateways.auth.interfaces import OAuthIdentity
from canterlot.models import AuthOutcome, AuthProviderName, AvatarSchema, LinkedProviderSchema, UserModel
from canterlot.models.user import UsernameStr
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


class OAuthSignInResult(BaseModel):
    outcome: AuthOutcome
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


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
            log.warning("Registration rejected: username conflict", reason="username_taken")
            raise UsernameAlreadyExistsError(f"Username '{request.username}' is already taken.")

        if await self.__user_repo.exists_by_email(request.email):
            log.warning("Registration rejected: email conflict", reason="email_registered")
            raise EmailAlreadyExistsError(f"Email '{request.email}' is already registered.")

        settings = get_settings()
        if (
            request.terms_version != settings.current_terms_version
            or request.privacy_version != settings.current_privacy_version
        ):
            log.warning("Registration rejected: submitted legal document version is stale")
            raise StaleLegalVersionError("The submitted terms/privacy version is out of date; reload and try again.")

        now = datetime.now(UTC)
        user = UserModel(
            name=request.name,
            username=request.username,
            email=request.email,
            hashed_password=hash_password(request.password),
            accepted_terms_version=request.terms_version,
            accepted_terms_at=now,
            accepted_privacy_version=request.privacy_version,
            accepted_privacy_at=now,
            profile_completed_at=now,
        )

        saved_user = await self.__user_repo.save(user)
        user_id = PydanticObjectId(saved_user.id)

        log = log.bind(user_id=str(user_id))

        if invited_by:
            await self.attribute_referral(invited_by)

        tokens = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, tokens.refresh_token)

        log.info("User registration transaction completed successfully")
        return RegisterResult(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            user_id=user_id,
        )

    async def attribute_referral(self, username: UsernameStr) -> None:
        log = logger.bind(invited_by=username)
        log.info("Processing referral growth attribution")
        await self.__user_repo.increment_referral_count_by_username(username)

    async def login_user(self, username: UsernameStr, plain_password: str) -> TokenResponse:
        log = logger.bind(username=username)
        log.info("Attempting user authentication")

        user = await self.__user_repo.find_by_username(username)
        if not (user and user.id and user.hashed_password and verify_password(plain_password, user.hashed_password)):
            log.warning("Authentication failed: invalid security credentials", error_type="credentials_mismatch")
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

        removed = await self.__user_repo.pull_refresh_token_by_id(user_id, old_token)
        if not removed:
            log.warning("Refresh rotation rejected: token already rotated, revoked, or unknown")
            raise InvalidCredentialsError("This refresh token has been revoked or invalidated.")

        tokens = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, tokens.refresh_token)

        log.info("Refresh token rotation completed successfully")
        return TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )

    async def logout(self, user_id: PydanticObjectId, token: str) -> None:
        log = logger.bind(user_id=str(user_id))
        log.info("Attempting to log out current session")

        removed = await self.__user_repo.pull_refresh_token_by_id(user_id, token)
        if not removed:
            log.warning("Logout no-op: refresh token already invalidated")
            return

        log.info("Session logged out successfully")

    def __create_tokens(self, user_id: PydanticObjectId) -> TokenPair:
        return TokenPair(
            access_token=create_access_token(user_id),
            refresh_token=create_refresh_token(user_id),
        )

    def __get_oauth_provider(self, provider: AuthProviderName) -> OAuthProvider:
        try:
            return self.__oauth_providers[provider]
        except KeyError:
            logger.bind(provider=provider).warning("Requested authentication provider is not configured")
            raise GatewayConfigurationError(f"The '{provider}' authentication provider is not available.") from None

    async def __issue_login_tokens(self, user_id: PydanticObjectId, outcome: AuthOutcome) -> OAuthSignInResult:
        tokens = self.__create_tokens(user_id)
        await self.__user_repo.push_refresh_token_by_id(user_id, tokens.refresh_token)

        return OAuthSignInResult(outcome=outcome, access_token=tokens.access_token, refresh_token=tokens.refresh_token)

    async def __sync_oauth_picture_metadata(
        self,
        user_id: PydanticObjectId,
        provider: AuthProviderName,
        identity: OAuthIdentity,
    ) -> None:
        # A sign-in/link with no picture claim leaves whatever was previously stored alone,
        # rather than clearing it.
        if not identity.picture:
            return
        picture = HttpUrl(identity.picture)

        await self.__user_repo.update_linked_provider_picture(user_id, provider, picture)

        oauth_provider = self.__oauth_providers.get(provider)
        if oauth_provider is None or not oauth_provider.supports_avatar:
            return

        current_avatar = await self.__user_repo.find_avatar_by_id(user_id)
        if current_avatar and current_avatar.source == provider:
            refreshed = AvatarSchema(source=provider, value=picture)
            await self.__user_repo.set_avatar(user_id, refreshed)

    async def sign_in_with_provider(self, provider: AuthProviderName, credential: str) -> OAuthSignInResult:
        log = logger.bind(provider=provider)
        log.info("Attempting OAuth provider sign-in")

        oauth_provider = self.__get_oauth_provider(provider)
        identity = await oauth_provider.verify(credential)

        existing_id = await self.__user_repo.find_id_by_linked_provider(provider, identity.external_id)
        if existing_id:
            log.info("OAuth identity matched an existing linked account", user_id=str(existing_id))
            await self.__sync_oauth_picture_metadata(existing_id, provider, identity)
            return await self.__issue_login_tokens(existing_id, AuthOutcome.LOGGED_IN)

        if await self.__user_repo.find_by_email(identity.email):
            log.warning("OAuth sign-in rejected: identity's email matches an account under a different auth method")
            raise OAuthLinkRequiredError("An account with this email already exists using a different sign-in method.")

        username_seed = identity.name or identity.email.split("@")[0]
        username = await make_username(username_seed, self.__user_repo.exists_by_username)
        picture = HttpUrl(identity.picture) if identity.picture else None
        avatar = AvatarSchema(source=provider, value=picture) if picture and oauth_provider.supports_avatar else None
        user = UserModel(
            name=identity.name or username,
            username=username,
            email=identity.email,
            linked_providers=[
                LinkedProviderSchema(
                    provider=provider,
                    external_id=identity.external_id,
                    picture_url=picture,
                )
            ],
            avatar=avatar,
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

    async def link_provider(
        self,
        user_id: PydanticObjectId,
        provider: AuthProviderName,
        credential: str,
        redirect_uri: str | None = None,
    ) -> None:
        log = logger.bind(user_id=str(user_id), provider=provider)
        log.info("Attempting to link a new authentication provider")

        identity = await self.__get_oauth_provider(provider).verify(credential, redirect_uri)

        existing_id = await self.__user_repo.find_id_by_linked_provider(provider, identity.external_id)
        if existing_id and existing_id != user_id:
            log.warning("Link rejected: credential already linked to a different account")
            raise AuthProviderAlreadyLinkedError(f"This {provider} account is already linked to a different user.")

        if existing_id:
            log.info("Provider already linked to this account, resyncing stored profile metadata")
            await self.__sync_oauth_picture_metadata(user_id, provider, identity)
            return

        linked = await self.__user_repo.add_linked_provider(
            user_id,
            LinkedProviderSchema(
                provider=provider,
                external_id=identity.external_id,
                picture_url=HttpUrl(identity.picture) if identity.picture else None,
            ),
        )
        if not linked:
            log.warning("Link rejected: a concurrent request linked this credential to a different account first")
            raise AuthProviderAlreadyLinkedError(f"This {provider} account is already linked to a different user.")

        log.info("Authentication provider linked successfully")

    async def revoke_provider_link(self, provider: AuthProviderName, external_id: str) -> None:
        log = logger.bind(provider=provider)
        log.info("Processing a provider-side revocation event")

        user_id = await self.__user_repo.find_id_by_linked_provider(provider, external_id)
        if not user_id:
            log.info("Revocation event matched no linked account, nothing to do")
            return

        # The revocation already happened on the provider's side regardless of our own rules, so this
        # unconditionally removes the link -- unlike disconnect_provider, it does not guard against being
        # the account's last remaining authentication method.
        await self.__user_repo.remove_linked_provider(user_id, provider)
        log.info("Authentication provider unlinked following a provider-side revocation", user_id=str(user_id))

    async def disconnect_provider(self, user_id: PydanticObjectId, provider: AuthProviderName) -> None:
        log = logger.bind(user_id=str(user_id), provider=provider)
        log.info("Attempting to disconnect an authentication provider")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warning("Disconnect aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        if not any(linked.provider == provider for linked in user.linked_providers):
            log.warning("Disconnect rejected: provider is not linked to this account")
            raise AuthProviderNotLinkedError(f"No linked '{provider}' account to disconnect.")

        remaining_providers = [linked for linked in user.linked_providers if linked.provider != provider]
        if not user.hashed_password and not remaining_providers:
            log.warning("Disconnect rejected: this is the account's last remaining authentication method")
            raise LastAuthenticationMethodError("Cannot disconnect your only remaining way to sign in.")

        await self.__user_repo.remove_linked_provider(user_id, provider)
        log.info("Authentication provider disconnected successfully")

    async def change_password(
        self, user_id: PydanticObjectId, current_password: str | None, new_password: str
    ) -> TokenResponse:
        log = logger.bind(user_id=str(user_id))
        log.info("Attempting password change")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warning("Password change aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        if user.hashed_password is not None:
            if not current_password or not verify_password(current_password, user.hashed_password):
                log.warning("Password change rejected: current password verification failed")
                raise IncorrectPasswordError("The current password provided is incorrect.")
        else:
            log.info("Setting an initial password for an OAuth-only account")

        tokens = self.__create_tokens(user_id)
        await self.__user_repo.change_password(user_id, hash_password(new_password), tokens.refresh_token)

        log.info("Password changed successfully, all other sessions revoked, new session token issued")
        return TokenResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)

    async def list_connected_providers(self, user_id: PydanticObjectId) -> ConnectedProvidersResponse:
        log = logger.bind(user_id=str(user_id))
        log.info("Fetching connected authentication providers")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warning("Lookup aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        return ConnectedProvidersResponse.from_model(user)
