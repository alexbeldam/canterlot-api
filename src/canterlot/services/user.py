import json
from datetime import UTC, datetime

import shortuuid
from beanie import PydanticObjectId

from canterlot.config import get_settings
from canterlot.constants import EMAIL_PREFERENCES_KEY_TEMPLATE
from canterlot.dto.book import RatedBook
from canterlot.exceptions import (
    AuthProviderNotLinkedError,
    InvalidCredentialsError,
    StaleLegalVersionError,
    UsernameAlreadyExistsError,
)
from canterlot.exceptions.user import UserNotFoundError
from canterlot.models.user import EmailPreferencesSchema, UserModel
from canterlot.pagination import Page, SortDirection
from canterlot.repositories import BookRepository, CacheRepository, ReadBookRepository, UserRepository
from canterlot.services.rated_books import resolve_rated_books_page
from canterlot.types import AuthProviderName, AvatarSchema, HttpsUrl, NormalizedEmailStr, PersonNameStr, UsernameStr
from canterlot.utils import get_logger
from canterlot.utils.security import UnsubscribeScope, UnsubscribeTokenData

logger = get_logger(__name__)


def _resolve_linked_provider_avatar_value(user: UserModel, provider: AuthProviderName) -> HttpsUrl:
    linked = next((entry for entry in user.linked_providers if entry.provider == provider), None)
    if linked is None or not linked.picture_url:
        raise AuthProviderNotLinkedError(
            f"No linked {provider} account with a profile picture is available to use as an avatar."
        )
    return linked.picture_url


class UserService:
    def __init__(
        self,
        user_repo: UserRepository,
        cache_repo: CacheRepository,
        read_book_repo: ReadBookRepository,
        book_repo: BookRepository,
    ):
        self.__user_repo = user_repo
        self.__cache_repo = cache_repo
        self.__read_book_repo = read_book_repo
        self.__book_repo = book_repo

    async def _invalidate_email_preferences_cache(self, email: NormalizedEmailStr) -> None:
        await self.__cache_repo.invalidate(EMAIL_PREFERENCES_KEY_TEMPLATE.format(email=email))

    async def get_by_username(self, username: UsernameStr) -> UserModel:
        user = await self.__user_repo.find_by_username(username)
        if not user:
            raise UserNotFoundError(f"User with username {username} not found")
        return user

    async def mark_book_read(
        self,
        user_id: PydanticObjectId,
        book_id: PydanticObjectId,
        rating: float | None = None,
    ) -> None:
        log = logger.bind(user_id=str(user_id), book_id=str(book_id), rating=rating)
        log.info("Marking book as read for user")

        await self.__read_book_repo.upsert(user_id=user_id, book_id=book_id, rating=rating)

        log.info("Book marked as read successfully")

    async def get_read_books(
        self,
        user_id: PydanticObjectId,
        page: int,
        limit: int,
        sort_direction: SortDirection = SortDirection.DESC,
    ) -> Page[RatedBook]:
        return await resolve_rated_books_page(
            self.__book_repo,
            self.__read_book_repo,
            user_id,
            page,
            limit,
            sort_direction,
        )

    async def update_profile(
        self,
        user: UserModel,
        name: PersonNameStr | None,
        username: UsernameStr | None,
    ) -> UserModel:
        log = logger.bind(user_id=str(user.id))
        log.info("Attempting profile update")

        if username is not None and username != user.username and await self.__user_repo.exists_by_username(username):
            log.warning("Profile update rejected: username conflict", reason="username_taken")
            raise UsernameAlreadyExistsError(f"Username '{username}' is already taken.")

        changed = await self.__user_repo.update_profile(PydanticObjectId(user.id), name=name, username=username)
        if not changed:
            log.warning("Profile update rejected: user no longer exists at write time")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        if name is not None:
            user.name = name
        if username is not None:
            user.username = username

        log.info("Profile updated successfully")
        return user

    async def set_avatar_source(self, user: UserModel, source: AuthProviderName) -> UserModel:
        log = logger.bind(user_id=str(user.id), source=str(source))
        log.info("Attempting to set avatar to a linked provider's photo")

        try:
            value = _resolve_linked_provider_avatar_value(user, source)
        except AuthProviderNotLinkedError:
            log.warning("Avatar update rejected: no linked account with a profile picture for this source")
            raise

        avatar = AvatarSchema(source=source, value=value)
        changed = await self.__user_repo.set_avatar(PydanticObjectId(user.id), avatar)
        if not changed:
            log.warning("Avatar update rejected: user no longer exists at write time")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        user.avatar = avatar
        log.info("Avatar set to linked provider's photo successfully")
        return user

    async def clear_avatar(self, user_id: PydanticObjectId) -> None:
        log = logger.bind(user_id=str(user_id))
        log.info("Attempting to clear the active avatar photo")

        changed = await self.__user_repo.clear_avatar(user_id)
        if not changed:
            log.warning("Avatar clear rejected: user no longer exists at write time")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        log.info("Avatar cleared, generated avatar now active")

    async def regenerate_avatar_seed(self, user: UserModel) -> UserModel:
        log = logger.bind(user_id=str(user.id))
        log.info("Attempting to regenerate the generated-avatar seed")

        new_seed = shortuuid.random()
        changed = await self.__user_repo.set_generated_avatar_seed(PydanticObjectId(user.id), new_seed)
        if not changed:
            log.warning("Seed regeneration rejected: user no longer exists at write time")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        user.generated_avatar_seed = new_seed
        log.info("Generated-avatar seed regenerated successfully")
        return user

    async def accept_legal_documents(
        self,
        user: UserModel,
        terms_version: int,
        privacy_version: int,
    ) -> UserModel:
        log = logger.bind(user_id=str(user.id), terms_version=terms_version, privacy_version=privacy_version)
        log.info("Attempting to record legal document acceptance")

        settings = get_settings().auth
        if terms_version != settings.current_terms_version or privacy_version != settings.current_privacy_version:
            log.warning(
                "Legal acceptance rejected: submitted version is stale",
                current_terms_version=settings.current_terms_version,
                current_privacy_version=settings.current_privacy_version,
            )
            raise StaleLegalVersionError("The submitted terms/privacy version is out of date; reload and try again.")

        now = datetime.now(UTC)
        profile_completed_at = user.profile_completed_at or now

        changed = await self.__user_repo.set_legal_acceptance(
            PydanticObjectId(user.id),
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

    async def process_unsubscribe(self, token_data: UnsubscribeTokenData) -> UnsubscribeScope:
        log = logger.bind(user_id=str(token_data.user_id), scope=str(token_data.scope))
        log.info("Processing unsubscribe request")

        user = await self.__user_repo.find_by_id(token_data.user_id)
        if user is None:
            log.warning("Unsubscribe rejected: user not found")
            raise UserNotFoundError("User associated with this unsubscribe token does not exist.")

        now = datetime.now(UTC)

        if token_data.scope == UnsubscribeScope.CLUB and token_data.club_id is not None:
            log.info("Applying club-scoped opt-out", club_id=str(token_data.club_id))
            await self.__user_repo.opt_out_club_by_id(token_data.user_id, token_data.club_id, now)

        elif token_data.scope == UnsubscribeScope.CATEGORY and token_data.category is not None:
            log.info("Applying category-scoped opt-out", category=str(token_data.category))
            await self.__user_repo.opt_out_category_by_id(token_data.user_id, token_data.category, now)

        await self._invalidate_email_preferences_cache(user.email)
        log.info("Unsubscribe request processed successfully")

        return token_data.scope

    async def is_verified_email(self, user_id: PydanticObjectId) -> bool:
        return await self.__user_repo.is_email_verified_by_id(user_id)

    async def find_by_id(self, user_id: PydanticObjectId) -> UserModel | None:
        return await self.__user_repo.find_by_id(user_id)

    async def get_by_id(self, user_id: PydanticObjectId) -> UserModel:
        user = await self.__user_repo.find_by_id(user_id)
        if user is None:
            raise UserNotFoundError("This user does not exist")
        return user

    async def get_by_ids(self, ids: list[PydanticObjectId]) -> list[UserModel]:
        return await self.__user_repo.get_by_ids(ids)

    async def get_id_by_username(self, username: UsernameStr) -> PydanticObjectId:
        user_id = await self.__user_repo.find_id_by_username(username)
        if user_id is None:
            raise UserNotFoundError(f"User with username '{username}' not found")
        return user_id

    async def find_by_identifier(self, identifier: NormalizedEmailStr | UsernameStr) -> UserModel | None:
        return await self.__user_repo.find_by_identifier(identifier)

    async def get_id_by_identifier(self, identifier: NormalizedEmailStr | UsernameStr) -> PydanticObjectId:
        user_id = await self.__user_repo.find_id_by_identifier(identifier)
        if user_id is None:
            raise UserNotFoundError(f"User with identifier '{identifier}' not found.")
        return user_id

    async def mark_email_as_verified(
        self,
        user_id: PydanticObjectId,
    ) -> None:
        timestamp = datetime.now(UTC)

        await self.__user_repo.mark_email_as_verified(user_id=user_id, verified_at=timestamp)
