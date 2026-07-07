from beanie import PydanticObjectId
from beanie.operators import ElemMatch, In, Pull, Push
from pydantic import BaseModel

from canterlot.models import AuthProviderName, LinkedProviderSchema, UserModel
from canterlot.models.user import UsernameStr
from canterlot.repositories import UserRepository
from canterlot.utils.format import NormalizedEmailStr


class UsernameProjection(BaseModel):
    username: UsernameStr


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

    async def find_by_email(self, email: NormalizedEmailStr) -> UserModel | None:
        return await UserModel.find_one(UserModel.email == email)

    async def find_by_linked_provider(self, provider: AuthProviderName, external_id: str) -> UserModel | None:
        return await UserModel.find_one(
            ElemMatch(UserModel.linked_providers, {"provider": provider, "external_id": external_id})
        )

    async def exists_by_username(self, username: UsernameStr) -> bool:
        return await UserModel.find(UserModel.username == username).count() > 0

    async def exists_by_email(self, email: NormalizedEmailStr) -> bool:
        return await UserModel.find(UserModel.email == email).count() > 0

    async def save(self, user: UserModel) -> UserModel:
        return await user.save()

    async def increment_referral_count_by_username(self, username: UsernameStr) -> None:
        await UserModel.find_one(UserModel.username == username).inc({UserModel.referral_count: 1})

    async def push_refresh_token_by_id(self, user_id: PydanticObjectId, token: str) -> None:
        await UserModel.find_one(UserModel.id == user_id).update_one(Push({UserModel.refresh_tokens: token}))

    async def pull_refresh_token_by_id(self, user_id: PydanticObjectId, token: str) -> None:
        await UserModel.find_one(UserModel.id == user_id).update_one(Pull({UserModel.refresh_tokens: token}))

    async def add_linked_provider(self, user_id: PydanticObjectId, entry: LinkedProviderSchema) -> None:
        await UserModel.find_one(UserModel.id == user_id).update_one(Push({UserModel.linked_providers: entry}))

    async def remove_linked_provider(self, user_id: PydanticObjectId, provider: AuthProviderName) -> None:
        await UserModel.find_one(UserModel.id == user_id).update_one(
            Pull({UserModel.linked_providers: {"provider": provider}})
        )
