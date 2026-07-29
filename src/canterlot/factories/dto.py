from typing import Any

from polyfactory import Use
from polyfactory.factories import DataclassFactory
from pydantic import HttpUrl

from canterlot.dto.auth import (
    AccessTokenResponse,
    CreateSessionRequest,
    LinkProviderRequest,
    RegisterResponse,
    TokenResponse,
    UserRegisterRequest,
)
from canterlot.dto.book import BookDetails, BookResponse, BookSearchResult
from canterlot.dto.catalog import BookSuggestionRequest, CatalogEntryResponse
from canterlot.dto.club import ClubCreateRequest, ClubOnboarding
from canterlot.dto.invite import CreateInviteRequest, InvitePreviewResponse, InviteTokenResponse
from canterlot.dto.user import UpdateProfileRequest
from canterlot.types import AuthProviderName, ExtensionType, InviteType, SessionType

from .base import BaseModelFactory


class AccessTokenResponseFactory(BaseModelFactory[AccessTokenResponse]):
    __model__ = AccessTokenResponse

    access_token = Use(lambda: AccessTokenResponseFactory.__faker__.uuid4())
    token_type = "bearer"


class BookDetailsFactory(BaseModelFactory[BookDetails]):
    __model__ = BookDetails

    page_count = Use(lambda: BookDetailsFactory.__faker__.random_int(min=50, max=1000))
    description = Use(lambda: BookDetailsFactory.__faker__.paragraph(nb_sentences=3))
    categories = Use(lambda: [BookDetailsFactory.__faker__.word() for _ in range(3)])


class BookSearchResultFactory(BaseModelFactory[BookSearchResult]):
    __model__ = BookSearchResult

    title = Use(lambda: BookSearchResultFactory.__faker__.sentence(nb_words=3))
    authors = Use(lambda: [BookSearchResultFactory.__faker__.name() for _ in range(2)])
    year = Use(lambda: BookSearchResultFactory.__faker__.random_int(min=1900, max=2025))
    isbn_10 = Use(lambda: BookSearchResultFactory.__faker__.isbn10(separator=""))
    isbn_13 = Use(lambda: BookSearchResultFactory.__faker__.isbn13(separator=""))
    languages = Use(lambda: [BookSearchResultFactory.__faker__.language_code() for _ in range(2)])
    cover_url = Use(lambda: BookSearchResultFactory.__faker__.image_url())


class BookSuggestionRequestFactory(BaseModelFactory[BookSuggestionRequest]):
    __model__ = BookSuggestionRequest

    title = Use(lambda: BookSuggestionRequestFactory.__faker__.sentence(nb_words=3))
    authors = Use(lambda: [BookSuggestionRequestFactory.__faker__.name() for _ in range(2)])
    year = Use(lambda: BookSuggestionRequestFactory.__faker__.random_int(min=1900, max=2025))
    page_count = Use(lambda: BookSuggestionRequestFactory.__faker__.random_int(min=50, max=1000))
    isbn_10 = Use(lambda: BookSuggestionRequestFactory.__faker__.isbn10(separator=""))
    isbn_13 = Use(lambda: BookSuggestionRequestFactory.__faker__.isbn13(separator=""))
    languages = Use(lambda: [BookSuggestionRequestFactory.__faker__.language_code() for _ in range(2)])
    description = Use(lambda: BookSuggestionRequestFactory.__faker__.paragraph(nb_sentences=3))
    categories = Use(lambda: [BookSuggestionRequestFactory.__faker__.word() for _ in range(3)])
    cover_url = Use(lambda: BookSuggestionRequestFactory.__faker__.image_url())


class BookResponseFactory(BaseModelFactory[BookResponse]):
    __model__ = BookResponse

    title = Use(lambda: BookResponseFactory.__faker__.sentence(nb_words=3))
    authors = Use(lambda: [BookResponseFactory.__faker__.name() for _ in range(2)])
    year = Use(lambda: BookResponseFactory.__faker__.random_int(min=1900, max=2025))
    page_count = Use(lambda: BookResponseFactory.__faker__.random_int(min=50, max=1000))
    isbn_10 = Use(lambda: BookResponseFactory.__faker__.isbn10(separator=""))
    isbn_13 = Use(lambda: BookResponseFactory.__faker__.isbn13(separator=""))
    languages = Use(lambda: [BookResponseFactory.__faker__.language_code() for _ in range(2)])
    description = Use(lambda: BookResponseFactory.__faker__.paragraph(nb_sentences=3))
    categories = Use(lambda: [BookResponseFactory.__faker__.word() for _ in range(3)])
    urls = Use(
        lambda: {
            ext: HttpUrl(
                "https://example.com/"
                f"{BookResponseFactory.__faker__.file_name(category='document', extension=ext.value)}"
            )
            for ext in BookResponseFactory.__faker__.random_elements(
                list(ExtensionType),
                length=BookResponseFactory.__faker__.random_int(min=1, max=2),
                unique=True,
            )
        }
    )


class CatalogEntryResponseFactory(BookResponseFactory):
    __model__ = CatalogEntryResponse

    suggested_by = Use(lambda: CatalogEntryResponseFactory.__faker__.user_name().replace(".", "_"))


class ClubCreateRequestFactory(BaseModelFactory[ClubCreateRequest]):
    __model__ = ClubCreateRequest

    name = Use(lambda: ClubCreateRequestFactory.__faker__.company())
    description = Use(lambda: ClubCreateRequestFactory.__faker__.paragraph(nb_sentences=3))
    preferred_languages = Use(lambda: [ClubCreateRequestFactory.__faker__.language_code() for _ in range(2)])


class ClubOnboardingFactory(DataclassFactory[ClubOnboarding]):
    __model__ = ClubOnboarding

    club_name = Use(lambda: ClubOnboardingFactory.__faker__.company())


class CreateInviteRequestFactory(BaseModelFactory[CreateInviteRequest]):
    __model__ = CreateInviteRequest

    @classmethod
    def build(cls, **kwargs: Any) -> CreateInviteRequest:
        invite_type = kwargs.get(
            "type",
            cls.__faker__.random_element(list(InviteType)),
        )
        if invite_type == InviteType.PUBLIC:
            kwargs.setdefault("email", None)
            kwargs.setdefault("username", None)
        elif invite_type == InviteType.DIRECT:
            if kwargs.get("username"):
                kwargs["email"] = None
            elif kwargs.get("email"):
                kwargs["username"] = None
            elif cls.__faker__.boolean():
                kwargs["email"] = cls.__faker__.email()
                kwargs["username"] = None
            else:
                kwargs["email"] = None
                kwargs["username"] = cls.__faker__.user_name().replace(".", "_")
        return super().build(**kwargs)


class CreateSessionRequestFactory(BaseModelFactory[CreateSessionRequest]):
    __model__ = CreateSessionRequest

    invite_id = None
    invited_by = None

    @classmethod
    def build(cls, **kwargs: Any) -> CreateSessionRequest:
        type = kwargs.get(
            "type",
            cls.__faker__.random_element(list(SessionType)),
        )
        if type == SessionType.PASSWORD:
            kwargs.setdefault("username", cls.__faker__.user_name().replace(".", "_"))
            kwargs.setdefault("password", cls.__faker__.password())
            kwargs.setdefault("provider", None)
            kwargs.setdefault("credential", None)
        else:
            kwargs.setdefault("username", None)
            kwargs.setdefault("password", None)
            kwargs.setdefault("provider", cls.__faker__.random_element(list(AuthProviderName)))
            kwargs.setdefault("credential", cls.__faker__.uuid4())
        return super().build(**kwargs)


class InvitePreviewResponseFactory(BaseModelFactory[InvitePreviewResponse]):
    __model__ = InvitePreviewResponse

    club_slug = Use(lambda: InvitePreviewResponseFactory.__faker__.slug())
    club_name = Use(lambda: InvitePreviewResponseFactory.__faker__.company())
    invited_by_username = Use(lambda: InvitePreviewResponseFactory.__faker__.user_name().replace(".", "_"))


class InviteTokenResponseFactory(BaseModelFactory[InviteTokenResponse]):
    __model__ = InviteTokenResponse

    invite_token = Use(lambda: InviteTokenResponseFactory.__faker__.uuid4()[:10])


class LinkProviderRequestFactory(BaseModelFactory[LinkProviderRequest]):
    __model__ = LinkProviderRequest

    credential = Use(lambda: LinkProviderRequestFactory.__faker__.uuid4())
    redirect_uri = None


class RegisterResponseFactory(AccessTokenResponseFactory):
    __model__ = RegisterResponse

    onboarding = None


class SearchResultFactory(BaseModelFactory[BookSearchResult]):
    __model__ = BookSearchResult

    title = Use(lambda: SearchResultFactory.__faker__.sentence(nb_words=3))
    authors = Use(lambda: [SearchResultFactory.__faker__.name() for _ in range(2)])
    year = Use(lambda: SearchResultFactory.__faker__.random_int(min=1900, max=2025))
    isbn_10 = Use(lambda: SearchResultFactory.__faker__.isbn10(separator=""))
    isbn_13 = Use(lambda: SearchResultFactory.__faker__.isbn13(separator=""))
    languages = Use(lambda: [SearchResultFactory.__faker__.language_code() for _ in range(2)])
    cover_url = Use(lambda: SearchResultFactory.__faker__.image_url())


class TokenResponseFactory(BaseModelFactory[TokenResponse]):
    __model__ = TokenResponse

    access_token = Use(lambda: TokenResponseFactory.__faker__.uuid4())
    refresh_token = Use(lambda: TokenResponseFactory.__faker__.uuid4())
    token_type = "bearer"


class UpdateProfileRequestFactory(BaseModelFactory[UpdateProfileRequest]):
    __model__ = UpdateProfileRequest

    name = Use(lambda: UpdateProfileRequestFactory.__faker__.name())
    username = Use(lambda: UpdateProfileRequestFactory.__faker__.user_name().replace(".", "_"))


class UserRegisterRequestFactory(BaseModelFactory[UserRegisterRequest]):
    __model__ = UserRegisterRequest

    name = Use(lambda: UserRegisterRequestFactory.__faker__.name())
    username = Use(lambda: UserRegisterRequestFactory.__faker__.user_name().replace(".", "_"))
    email = Use(lambda: UserRegisterRequestFactory.__faker__.email())
    password = Use(lambda: UserRegisterRequestFactory.__faker__.password(length=12))
    terms_version = 1
    privacy_version = 1
    invite_id = None
    invited_by = None
