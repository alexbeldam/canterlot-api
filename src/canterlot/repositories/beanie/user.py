from typing import cast

from beanie import PydanticObjectId
from beanie.operators import ElemMatch, In, Pull, Push
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import DuplicateKeyError
from pymongo.results import UpdateResult

from canterlot.models import AuthProviderName, AvatarSchema, LinkedProviderSchema, UserModel
from canterlot.models.user import PersonNameStr, UsernameStr
from canterlot.repositories import UserRepository
from canterlot.utils.format import HttpsUrl, NormalizedEmailStr


class UsernameProjection(BaseModel):
    username: UsernameStr


class IdProjection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: PydanticObjectId = Field(alias="_id")


class AvatarProjection(BaseModel):
    avatar: AvatarSchema | None = None


class BeanieUserRepository(UserRepository):
    async def find_by_id(self, user_id: PydanticObjectId) -> UserModel | None:
        return await UserModel.get(user_id)

    async def find_username_by_id(self, user_id: PydanticObjectId) -> UsernameStr | None:
        p = await UserModel.find_one(UserModel.id == user_id).project(UsernameProjection)

        if not p or not p.username:
            return None
        return p.username

    async def find_usernames_by_ids(self, user_ids: list[PydanticObjectId]) -> dict[PydanticObjectId, UsernameStr]:
        if not user_ids:
            return {}

        users = await UserModel.find(In(UserModel.id, user_ids)).to_list()

        return {PydanticObjectId(u.id): u.username for u in users}

    async def find_by_username(self, username: UsernameStr) -> UserModel | None:
        return await UserModel.find_one(UserModel.username == username)

    async def find_id_by_username(self, username: UsernameStr) -> PydanticObjectId | None:
        projection = await UserModel.find_one(UserModel.username == username).project(IdProjection)

        if not projection:
            return None
        return projection.id

    async def find_by_email(self, email: NormalizedEmailStr) -> UserModel | None:
        return await UserModel.find_one(UserModel.email == email)

    async def find_id_by_linked_provider(self, provider: AuthProviderName, external_id: str) -> PydanticObjectId | None:
        projection = await UserModel.find_one(
            ElemMatch(UserModel.linked_providers, {"provider": provider, "external_id": external_id})
        ).project(IdProjection)

        if not projection:
            return None
        return projection.id

    async def exists_by_username(self, username: UsernameStr) -> bool:
        return await UserModel.find(UserModel.username == username).count() > 0

    async def exists_by_email(self, email: NormalizedEmailStr) -> bool:
        return await UserModel.find(UserModel.email == email).count() > 0

    async def save(self, user: UserModel) -> UserModel:
        return await user.save()

    async def save_new_oauth_account(self, user: UserModel) -> UserModel | None:
        try:
            return await user.save()
        except DuplicateKeyError:
            return None

    async def increment_referral_count_by_username(self, username: UsernameStr) -> None:
        await UserModel.find_one(UserModel.username == username).inc({UserModel.referral_count: 1})

    async def push_read_book_by_id(self, user_id, read_book):
        await UserModel.find_one(UserModel.id == user_id).update_one(Push({UserModel.books_read: read_book}))

    async def push_refresh_token_by_id(self, user_id: PydanticObjectId, token: str) -> None:
        await UserModel.find_one(UserModel.id == user_id).update_one(Push({UserModel.refresh_tokens: token}))

    async def pull_refresh_token_by_id(self, user_id: PydanticObjectId, token: str) -> bool:
        result = await UserModel.find_one(UserModel.id == user_id, {"refresh_tokens": token}).update_one(
            Pull({UserModel.refresh_tokens: token})
        )
        return cast(UpdateResult, result).matched_count > 0

    async def add_linked_provider(self, user_id: PydanticObjectId, entry: LinkedProviderSchema) -> bool:
        try:
            await UserModel.find_one(UserModel.id == user_id).update_one(Push({UserModel.linked_providers: entry}))
            return True
        except DuplicateKeyError:
            return False

    async def remove_linked_provider(self, user_id: PydanticObjectId, provider: AuthProviderName) -> None:
        await UserModel.find_one(UserModel.id == user_id).update_one(
            Pull({UserModel.linked_providers: {"provider": provider}})
        )

    async def update_linked_provider_picture(
        self, user_id: PydanticObjectId, provider: AuthProviderName, picture_url: HttpsUrl
    ) -> None:
        await UserModel.find_one(UserModel.id == user_id).update_one(
            {"$set": {"linked_providers.$[target].picture_url": picture_url}},
            array_filters=[{"target.provider": provider}],
        )

    async def find_avatar_by_id(self, user_id: PydanticObjectId) -> AvatarSchema | None:
        p = await UserModel.find_one(UserModel.id == user_id).project(AvatarProjection)

        if not p:
            return None
        return p.avatar

    async def set_avatar(self, user_id: PydanticObjectId, avatar: AvatarSchema) -> bool:
        result = await UserModel.find_one(UserModel.id == user_id).update_one({"$set": {"avatar": avatar}})
        return cast(UpdateResult, result).matched_count > 0

    async def clear_avatar(self, user_id: PydanticObjectId) -> bool:
        result = await UserModel.find_one(UserModel.id == user_id).update_one({"$set": {"avatar": None}})
        return cast(UpdateResult, result).matched_count > 0

    async def set_generated_avatar_seed(self, user_id: PydanticObjectId, seed: str) -> bool:
        result = await UserModel.find_one(UserModel.id == user_id).update_one({"$set": {"generated_avatar_seed": seed}})
        return cast(UpdateResult, result).matched_count > 0

    async def update_profile(
        self,
        user_id: PydanticObjectId,
        name: PersonNameStr | None = None,
        username: UsernameStr | None = None,
    ) -> bool:
        updates: dict[str, object] = {}
        if name is not None:
            updates["name"] = name
        if username is not None:
            updates["username"] = username

        result = await UserModel.find_one(UserModel.id == user_id).update_one({"$set": updates})

        return cast(UpdateResult, result).matched_count > 0

    async def change_password(self, user_id: PydanticObjectId, hashed_password: str, new_refresh_token: str) -> None:
        await UserModel.find_one(UserModel.id == user_id).update_one(
            {
                "$set": {
                    UserModel.hashed_password: hashed_password,
                    UserModel.refresh_tokens: [new_refresh_token],
                }
            }
        )
