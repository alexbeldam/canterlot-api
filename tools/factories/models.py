from datetime import UTC, datetime, timedelta
from typing import cast

import shortuuid
from beanie import PydanticObjectId
from polyfactory import Use
from pydantic import HttpUrl

from canterlot.emails.core.enums import EmailCategory
from canterlot.models import BookModel, CatalogEntryModel, ClubModel, InviteModel, ReadBookModel, UserModel
from canterlot.models.book import LinkCandidate
from canterlot.models.club import PendingApprovalSchema
from canterlot.models.user import EmailPreferencesSchema, LinkedProviderSchema
from canterlot.models.verification import VerificationCodeModel
from canterlot.types import (
    AvatarSchema,
    BadgeReason,
    EarnedBadgeSchema,
    ExtensionType,
    InviteType,
    MemberRole,
    MemberSchema,
)

from .base import BaseDocumentFactory, BaseModelFactory, MemberFactory


class BaseLinkCadidateFactory[T: LinkCandidate](BaseModelFactory[T]):
    __is_base_factory__ = True

    title = Use(lambda: BaseLinkCadidateFactory.__faker__.sentence(nb_words=3))
    authors = Use(lambda: [BaseLinkCadidateFactory.__faker__.name() for _ in range(2)])
    languages = Use(lambda: [BaseLinkCadidateFactory.__faker__.language_code() for _ in range(2)])

    @classmethod
    def build(cls, factory_use_construct: bool = False, **kwargs) -> T:
        ext = kwargs.get("extension", cls.__faker__.random_element(list(ExtensionType)))

        kwargs.setdefault(
            "url",
            HttpUrl(f"https://example.com/{cls.__faker__.file_name(category='document', extension=ext.value)}"),
        )

        return super().build(factory_use_construct, **kwargs)


class LinkCadidateFactory(BaseLinkCadidateFactory[LinkCandidate]):
    __model__ = LinkCandidate


class BookFactory(BaseDocumentFactory[BookModel]):
    __model__ = BookModel

    title = Use(lambda: BookFactory.__faker__.sentence(nb_words=3))
    authors = Use(lambda: [BookFactory.__faker__.name() for _ in range(2)])
    year = Use(lambda: BookFactory.__faker__.random_int(min=1900, max=2025))
    page_count = Use(lambda: BookFactory.__faker__.random_int(min=50, max=1000))
    isbn_10 = Use(lambda: BookFactory.__faker__.isbn10(separator=""))
    isbn_13 = Use(lambda: BookFactory.__faker__.isbn13(separator=""))
    languages = Use(lambda: [BookFactory.__faker__.language_code() for _ in range(2)])
    description = Use(lambda: BookFactory.__faker__.paragraph(nb_sentences=3))
    categories = Use(lambda: [BookFactory.__faker__.word() for _ in range(3)])
    cover_url = Use(lambda: BookFactory.__faker__.image_url(width=500, height=700))
    urls = Use(
        lambda: {
            ext: HttpUrl(
                f"https://example.com/{BookFactory.__faker__.file_name(category='document', extension=ext.value)}"
            )
            for ext in BookFactory.__faker__.random_elements(
                list(ExtensionType),
                length=BookFactory.__faker__.random_int(min=1, max=2),
                unique=True,
            )
        }
    )


class CatalogEntryFactory(BaseModelFactory[CatalogEntryModel]):
    __model__ = CatalogEntryModel


class ClubFactory(BaseDocumentFactory[ClubModel]):
    __model__ = ClubModel

    name = Use(lambda: ClubFactory.__faker__.company())
    description = Use(lambda: ClubFactory.__faker__.paragraph(nb_sentences=3))
    slug = Use(lambda: ClubFactory.__faker__.slug())
    allow_suggestions = Use(lambda: ClubFactory.__faker__.boolean())
    preferred_languages = Use(lambda: [ClubFactory.__faker__.language_code() for _ in range(2)])
    members = Use(lambda: ClubFactory._generate_members())
    banned_users = Use(lambda: cast(list[PydanticObjectId], []))
    pending_approvals = Use(lambda: cast(list[PendingApprovalSchema], []))
    catalog = Use(lambda: cast(list[CatalogEntryModel], []))
    ownership_transferred_at = None
    protected_former_owner_id = None

    @classmethod
    def _generate_members(cls) -> list[MemberSchema]:
        faker = cls.__faker__
        count = faker.random_int(min=1, max=5)

        roles: list[MemberRole] = [MemberRole.OWNER]
        non_owner_roles = [role for role in MemberRole if role != MemberRole.OWNER]

        for _ in range(count - 1):
            roles.append(faker.random_element(non_owner_roles))

        faker.random.shuffle(roles)

        return [MemberFactory.build(role=role) for role in roles]


class InviteFactory(BaseDocumentFactory[InviteModel]):
    __model__ = InviteModel

    id = Use(lambda: shortuuid.random(length=10))
    uses_count = 0
    is_active = True

    @classmethod
    def build(cls, factory_use_construct: bool = False, **kwargs) -> InviteModel:
        invite_type = kwargs.get("type", cls.__faker__.random_element(list(InviteType)))

        if invite_type == InviteType.PUBLIC:
            kwargs.setdefault("target_email", None)
            kwargs.setdefault("target_user_id", None)
            kwargs.setdefault("expires_at", None)
            kwargs.setdefault("created_by", None)
        elif invite_type == InviteType.DIRECT:
            kwargs.setdefault("expires_at", datetime.now(UTC) + timedelta(days=7))
            kwargs.setdefault("created_by", PydanticObjectId())

            if not (kwargs.get("target_email") or kwargs.get("target_user_id")):
                if cls.__faker__.boolean():
                    kwargs.setdefault("target_email", cls.__faker__.email())
                    kwargs.setdefault("target_user_id", None)
                else:
                    kwargs.setdefault("target_email", None)
                    kwargs.setdefault("target_user_id", PydanticObjectId())

        return super().build(factory_use_construct, **kwargs)


class EmailPreferencesFactory(BaseModelFactory[EmailPreferencesSchema]):
    __model__ = EmailPreferencesSchema
    __set_as_default_factory_for_type__ = True

    delivery_failed = False
    categories_opt_out = Use(lambda: cast(dict[EmailCategory, datetime], {}))
    categories_system_suppressed = Use(lambda: cast(dict[EmailCategory, datetime], {}))
    clubs_opt_out = Use(lambda: cast(dict[PydanticObjectId, datetime], {}))
    verified_at = Use(
        lambda: EmailPreferencesFactory.__faker__.date_time_between(start_date="-1y", end_date="now", tzinfo=UTC)
    )


class AvatarFactory(BaseModelFactory[AvatarSchema]):
    __model__ = AvatarSchema
    __set_as_default_factory_for_type__ = True

    value = Use(lambda: AvatarFactory.__faker__.image_url(width=300, height=300))


class LinkedProviderFactory(BaseModelFactory[LinkedProviderSchema]):
    __model__ = LinkedProviderSchema
    __set_as_default_factory_for_type__ = True

    external_id = Use(lambda: LinkedProviderFactory.__faker__.uuid4())
    picture_url = Use(lambda: LinkedProviderFactory.__faker__.image_url(width=300, height=300))


class UserFactory(BaseDocumentFactory[UserModel]):
    __model__ = UserModel

    name = Use(lambda: UserFactory.__faker__.name())
    username = Use(lambda: UserFactory.__faker__.user_name().replace(".", "_"))
    email = Use(lambda: UserFactory.__faker__.email())
    hashed_password = Use(lambda: UserFactory.__faker__.sha256())
    linked_providers = Use(lambda: cast(list[LinkedProviderSchema], []))
    avatar = None
    generated_avatar_seed = Use(lambda: shortuuid.random())
    referral_count = 0
    badges = Use(lambda: [EarnedBadgeSchema(reason=BadgeReason.JOINED)])
    refresh_tokens = Use(lambda: cast(list[str], []))
    accepted_terms_version = 1
    accepted_terms_at = Use(
        lambda: UserFactory.__faker__.date_time_between(start_date="-1y", end_date="now", tzinfo=UTC)
    )
    accepted_privacy_version = 1
    accepted_privacy_at = Use(
        lambda: UserFactory.__faker__.date_time_between(start_date="-1y", end_date="now", tzinfo=UTC)
    )
    profile_completed_at = Use(
        lambda: UserFactory.__faker__.date_time_between(start_date="-1y", end_date="now", tzinfo=UTC)
    )
    last_seen_at = Use(lambda: UserFactory.__faker__.date_time_between(start_date="-2m", end_date="now", tzinfo=UTC))


class ReadBookFactory(BaseDocumentFactory[ReadBookModel]):
    __model__ = ReadBookModel

    rating = Use(
        lambda: ReadBookFactory.__faker__.random_element([None, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0])
    )


class VerificationCodeFactory(BaseDocumentFactory[VerificationCodeModel]):
    __model__ = VerificationCodeModel

    code_hash = Use(lambda: VerificationCodeFactory.__faker__.sha256())
    expires_at = Use(lambda: datetime.now(UTC) + timedelta(minutes=10))
    is_active = True
