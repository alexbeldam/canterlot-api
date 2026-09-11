from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Response, status

from canterlot.dto.auth import (
    AccessTokenResponse,
    ConnectedProvidersResponse,
    LinkProviderRequest,
    RegisterResponse,
    UserRegisterRequest,
)
from canterlot.dto.book import ReadBooksFilters
from canterlot.dto.user import (
    ChangePasswordRequest,
    CreatePasswordRequest,
    LegalAcceptanceRequest,
    MarkBookReadRequest,
    PaginatedReadBooksResponse,
    ReadBookSummaryDTO,
    SetAvatarRequest,
    UpdateProfileRequest,
    UserProfileResponse,
)
from canterlot.models.user import UserModel
from canterlot.routers.cookies import set_refresh_token_cookie
from canterlot.routers.responses import (
    ACCEPT_LEGAL_DOCUMENTS_RESPONSES,
    CHANGE_PASSWORD_RESPONSES,
    CLEAR_AVATAR_RESPONSES,
    CREATE_PASSWORD_RESPONSES,
    DISCONNECT_PROVIDER_RESPONSES,
    GET_CONNECTED_PROVIDERS_RESPONSES,
    GET_OWN_PROFILE_RESPONSES,
    GET_READ_BOOKS_RESPONSES,
    LINK_PROVIDER_RESPONSES,
    MARK_BOOK_READ_RESPONSES,
    REGENERATE_AVATAR_SEED_RESPONSES,
    REGISTER_RESPONSES,
    SET_AVATAR_RESPONSES,
    UPDATE_PROFILE_RESPONSES,
)
from canterlot.services import UserService
from canterlot.types import AuthProviderName
from canterlot.use_cases import (
    ChangePasswordUseCase,
    CreatePasswordUseCase,
    DisconnectAuthProviderUseCase,
    LinkAuthProviderUseCase,
    RegisterUserUseCase,
)

from .dependencies.providers import (
    get_book_id_from_identifier,
    get_change_password_use_case,
    get_create_password_use_case,
    get_current_user,
    get_current_user_id,
    get_disconnect_auth_provider_use_case,
    get_link_auth_provider_use_case,
    get_register_user_use_case,
    get_user_service,
)
from .dependencies.rate_limiter import (
    rate_limit_password_change_attempt,
    rate_limit_provider_mutation_attempt,
    rate_limit_register_attempt,
)

router = APIRouter(prefix="/users", tags=["Users"])
_profile = APIRouter(prefix="/me", tags=["Users"])
_oauth = APIRouter(prefix="/auth-providers", tags=["Users"])
_read_books = APIRouter(prefix="/read-books", tags=["Users"])


@router.post(
    "",
    operation_id="register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_register_attempt)],
    responses=REGISTER_RESPONSES,
)
async def register(
    payload: UserRegisterRequest,
    response: Response,
    use_case: Annotated[RegisterUserUseCase, Depends(get_register_user_use_case)],
) -> RegisterResponse:
    result = await use_case.execute(payload)

    set_refresh_token_cookie(response, result.refresh_token)
    response.headers["Location"] = "/v1/users/me"

    return result.response


@_profile.get(
    "",
    operation_id="getOwnProfile",
    response_model=UserProfileResponse,
    responses=GET_OWN_PROFILE_RESPONSES,
)
async def get_own_profile(current_user: Annotated[UserModel, Depends(get_current_user)]) -> UserProfileResponse:
    return UserProfileResponse.from_model(current_user)


@_profile.patch(
    "",
    operation_id="updateProfile",
    response_model=UserProfileResponse,
    responses=UPDATE_PROFILE_RESPONSES,
)
async def update_profile(
    payload: UpdateProfileRequest,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    updated = await user_service.update_profile(current_user, name=payload.name, username=payload.username)
    return UserProfileResponse.from_model(updated)


@_profile.put(
    "/password",
    operation_id="changePassword",
    response_model=AccessTokenResponse,
    dependencies=[Depends(rate_limit_password_change_attempt)],
    responses=CHANGE_PASSWORD_RESPONSES,
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    response: Response,
    use_case: Annotated[ChangePasswordUseCase, Depends(get_change_password_use_case)],
) -> AccessTokenResponse:
    result = await use_case.execute(
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )

    set_refresh_token_cookie(response, result.refresh_token)

    return result.response


@_profile.post(
    "/password",
    operation_id="createPassword",
    response_model=AccessTokenResponse,
    dependencies=[Depends(rate_limit_password_change_attempt)],
    responses=CREATE_PASSWORD_RESPONSES,
)
async def create_password(
    payload: CreatePasswordRequest,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    response: Response,
    use_case: Annotated[CreatePasswordUseCase, Depends(get_create_password_use_case)],
) -> AccessTokenResponse:
    result = await use_case.execute(
        user=current_user,
        password=payload.password,
    )

    set_refresh_token_cookie(response, result.refresh_token)

    return result.response


@_profile.put(
    "/avatar",
    operation_id="setAvatar",
    response_model=UserProfileResponse,
    responses=SET_AVATAR_RESPONSES,
)
async def set_avatar(
    payload: SetAvatarRequest,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    updated = await user_service.set_avatar_source(current_user, payload.source)

    return UserProfileResponse.from_model(updated)


@_profile.delete(
    "/avatar",
    operation_id="clearAvatar",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=CLEAR_AVATAR_RESPONSES,
)
async def clear_avatar(
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> None:
    await user_service.clear_avatar(current_user_id)


@_profile.post(
    "/avatar/seed",
    operation_id="regenerateAvatarSeed",
    response_model=UserProfileResponse,
    responses=REGENERATE_AVATAR_SEED_RESPONSES,
)
async def regenerate_avatar_seed(
    current_user: Annotated[UserModel, Depends(get_current_user)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    updated = await user_service.regenerate_avatar_seed(current_user)

    return UserProfileResponse.from_model(updated)


@_profile.post(
    "/legal-acceptance",
    operation_id="acceptLegalDocuments",
    response_model=UserProfileResponse,
    responses=ACCEPT_LEGAL_DOCUMENTS_RESPONSES,
)
async def accept_legal_documents(
    payload: LegalAcceptanceRequest,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserProfileResponse:
    updated = await user_service.accept_legal_documents(
        current_user,
        terms_version=payload.terms_version,
        privacy_version=payload.privacy_version,
    )

    return UserProfileResponse.from_model(updated)


@_oauth.get(
    "",
    operation_id="getConnectedProviders",
    response_model=ConnectedProvidersResponse,
    responses=GET_CONNECTED_PROVIDERS_RESPONSES,
)
async def get_connected_providers(
    current_user: Annotated[UserModel, Depends(get_current_user)],
) -> ConnectedProvidersResponse:
    return ConnectedProvidersResponse.from_model(current_user)


@_oauth.post(
    "/{provider}",
    operation_id="linkProvider",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit_provider_mutation_attempt)],
    responses=LINK_PROVIDER_RESPONSES,
)
async def link_provider(
    provider: AuthProviderName,
    payload: LinkProviderRequest,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    use_case: Annotated[LinkAuthProviderUseCase, Depends(get_link_auth_provider_use_case)],
) -> None:
    await use_case.execute(
        user=current_user,
        provider=provider,
        credential=payload.credential,
        redirect_uri=payload.redirect_uri,
    )


@_oauth.delete(
    "/{provider}",
    operation_id="disconnectProvider",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit_provider_mutation_attempt)],
    responses=DISCONNECT_PROVIDER_RESPONSES,
)
async def disconnect_provider(
    provider: AuthProviderName,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    use_case: Annotated[DisconnectAuthProviderUseCase, Depends(get_disconnect_auth_provider_use_case)],
) -> None:
    await use_case.execute(
        user=current_user,
        provider=provider,
    )


@_read_books.get(
    "",
    operation_id="getReadBooks",
    response_model=PaginatedReadBooksResponse,
    responses=GET_READ_BOOKS_RESPONSES,
)
async def get_read_books(
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    filters: Annotated[ReadBooksFilters, Depends()],
) -> PaginatedReadBooksResponse:
    page = await user_service.get_read_books(current_user_id, filters.page, filters.limit, filters.sort_direction)
    return page.map(ReadBookSummaryDTO.from_model)


@_read_books.put(
    "/{identifier}",
    operation_id="markBookRead",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=MARK_BOOK_READ_RESPONSES,
)
async def mark_book_read(
    book_id: Annotated[PydanticObjectId, Depends(get_book_id_from_identifier)],
    current_user_id: Annotated[PydanticObjectId, Depends(get_current_user_id)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    payload: MarkBookReadRequest | None = None,
) -> None:
    rating = payload.rating if payload is not None else None
    await user_service.mark_book_read(user_id=current_user_id, book_id=book_id, rating=rating)


_profile.include_router(_oauth)
_profile.include_router(_read_books)
router.include_router(_profile)
