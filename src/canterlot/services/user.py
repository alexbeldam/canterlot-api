import json
from datetime import UTC, datetime

import shortuuid
from beanie import PydanticObjectId

from canterlot.config import get_settings
from canterlot.constants import EMAIL_PREFERENCES_KEY_TEMPLATE
from canterlot.exceptions import (
    AuthProviderNotLinkedError,
    InvalidCredentialsError,
    StaleLegalVersionError,
    UsernameAlreadyExistsError,
)
from canterlot.models.book import ReadBook
from canterlot.models.user import (
    AvatarSchema,
    EmailPreferencesSchema,
    PersonNameStr,
    UserModel,
    UsernameStr,
)
from canterlot.repositories import CacheRepository, UserRepository
from canterlot.types import AuthProviderName, HttpsUrl, NormalizedEmailStr
from canterlot.utils import get_logger

logger = get_logger(__name__)


def _resolve_linked_provider_avatar_value(user: UserModel, provider: AuthProviderName) -> HttpsUrl:
    linked = next((entry for entry in user.linked_providers if entry.provider == provider), None)
    if linked is None or not linked.picture_url:
        raise AuthProviderNotLinkedError(
            f"No linked {provider} account with a profile picture is available to use as an avatar."
        )
    return linked.picture_url


class UserService:
    def __init__(self, user_repo: UserRepository, cache_repo: CacheRepository):
        self.__user_repo = user_repo
        self.__cache_repo = cache_repo

    async def mark_book_read(self, user_id: PydanticObjectId, book_id: PydanticObjectId) -> None:
        log = logger.bind(user_id=str(user_id), book_id=str(book_id))
        log.info("Marking book as read for user")

        await self.__user_repo.push_read_book_by_id(user_id=user_id, read_book=ReadBook(id=book_id))

        log.info("Book marked as read successfully")

    async def get_profile(self, user_id: PydanticObjectId) -> UserModel:
        log = logger.bind(user_id=str(user_id))
        log.info("Fetching own profile")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warning("Profile fetch aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        return user

    async def find_profile_by_id(self, user_id: PydanticObjectId) -> UserModel | None:
        return await self.__user_repo.find_by_id(user_id)

    async def update_profile(
        self,
        user_id: PydanticObjectId,
        name: PersonNameStr | None,
        username: UsernameStr | None,
    ) -> UserModel:
        log = logger.bind(user_id=str(user_id))
        log.info("Attempting profile update")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warning("Profile update aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        if username is not None and username != user.username and await self.__user_repo.exists_by_username(username):
            log.warning("Profile update rejected: username conflict", reason="username_taken")
            raise UsernameAlreadyExistsError(f"Username '{username}' is already taken.")

        changed = await self.__user_repo.update_profile(user_id, name=name, username=username)
        if not changed:
            log.warning("Profile update rejected: user no longer exists at write time")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        if name is not None:
            user.name = name
        if username is not None:
            user.username = username

        log.info("Profile updated successfully")
        return user

    async def set_avatar_source(self, user_id: PydanticObjectId, source: AuthProviderName) -> UserModel:
        log = logger.bind(user_id=str(user_id), source=str(source))
        log.info("Attempting to set avatar to a linked provider's photo")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warning("Avatar update aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        try:
            value = _resolve_linked_provider_avatar_value(user, source)
        except AuthProviderNotLinkedError:
            log.warning("Avatar update rejected: no linked account with a profile picture for this source")
            raise

        avatar = AvatarSchema(source=source, value=value)
        changed = await self.__user_repo.set_avatar(user_id, avatar)
        if not changed:
            log.warning("Avatar update rejected: user no longer exists at write time")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        user.avatar = avatar
        log.info("Avatar set to linked provider's photo successfully")
        return user

    async def clear_avatar(self, user_id: PydanticObjectId) -> UserModel:
        log = logger.bind(user_id=str(user_id))
        log.info("Attempting to clear the active avatar photo")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warning("Avatar clear aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        changed = await self.__user_repo.clear_avatar(user_id)
        if not changed:
            log.warning("Avatar clear rejected: user no longer exists at write time")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        user.avatar = None
        log.info("Avatar cleared, generated avatar now active")
        return user

    async def regenerate_avatar_seed(self, user_id: PydanticObjectId) -> UserModel:
        log = logger.bind(user_id=str(user_id))
        log.info("Attempting to regenerate the generated-avatar seed")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warning("Seed regeneration aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        new_seed = shortuuid.random()
        changed = await self.__user_repo.set_generated_avatar_seed(user_id, new_seed)
        if not changed:
            log.warning("Seed regeneration rejected: user no longer exists at write time")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        user.generated_avatar_seed = new_seed
        log.info("Generated-avatar seed regenerated successfully")
        return user

    async def accept_legal_documents(
        self,
        user_id: PydanticObjectId,
        terms_version: int,
        privacy_version: int,
    ) -> UserModel:
        log = logger.bind(user_id=str(user_id), terms_version=terms_version, privacy_version=privacy_version)
        log.info("Attempting to record legal document acceptance")

        settings = get_settings()
        if terms_version != settings.current_terms_version or privacy_version != settings.current_privacy_version:
            log.warning(
                "Legal acceptance rejected: submitted version is stale",
                current_terms_version=settings.current_terms_version,
                current_privacy_version=settings.current_privacy_version,
            )
            raise StaleLegalVersionError("The submitted terms/privacy version is out of date; reload and try again.")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warning("Legal acceptance aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        now = datetime.now(UTC)
        profile_completed_at = user.profile_completed_at or now

        changed = await self.__user_repo.set_legal_acceptance(
            user_id,
            terms_version=terms_version,
            terms_at=now,
            privacy_version=privacy_version,
            privacy_at=now,
            profile_completed_at=profile_completed_at,
        )
        if not changed:
            log.warning("Legal acceptance rejected: user no longer exists at write time")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        user.accepted_terms_version = terms_version
        user.accepted_terms_at = now
        user.accepted_privacy_version = privacy_version
        user.accepted_privacy_at = now
        user.profile_completed_at = profile_completed_at

        log.info("Legal document acceptance recorded successfully")
        return user

    async def get_email_preferences(self, email: NormalizedEmailStr) -> EmailPreferencesSchema:
        log = logger.bind(email=email)
        log.info("Fetching email preferences")

        cached_map = await self.__cache_repo.find(EMAIL_PREFERENCES_KEY_TEMPLATE.format(email=email))

        if cached_map and "payload" in cached_map:
            try:
                raw_json = json.loads(cached_map["payload"])

                log.info("Email preferences fetched successfully from cache")

                return EmailPreferencesSchema.model_validate(raw_json)
            except (json.JSONDecodeError, ValueError):
                log.warning("Discarding malformed cache mapping payload, falling back to database")

        db_prefs = await self.__user_repo.find_email_preferences_by_email(email)

        if db_prefs is None:
            log.info("Email address does not match an active user record, returning standard default layout")

            return EmailPreferencesSchema()

        serialized_blob = db_prefs.model_dump(mode="json")
        await self.__cache_repo.save(
            key=EMAIL_PREFERENCES_KEY_TEMPLATE.format(email=email),
            mapping={"payload": json.dumps(serialized_blob)},
            expire_seconds=86400,  # 24 hours
        )

        log.info("Email preferences fetched from database and synchronized into cache")
        return db_prefs
