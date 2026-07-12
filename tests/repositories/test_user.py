from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId

from canterlot.models.book import ReadBook
from canterlot.models.enums import AuthProviderName
from canterlot.models.user import LinkedProviderSchema, UserModel
from canterlot.repositories.beanie.user import BeanieUserRepository

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieUserRepository()

_counter = 0


def _id(user: UserModel) -> PydanticObjectId:
    return PydanticObjectId(user.id)


async def _user(**overrides: object) -> UserModel:
    global _counter
    _counter += 1
    defaults = {
        "name": "Twilight Sparkle",
        "username": f"user{_counter}",
        "email": f"user{_counter}@example.com",
    }
    return await UserModel(**{**defaults, **overrides}).insert()


def describe_find_by_id():
    async def it_finds_a_user_by_id():
        user = await _user()

        found = await repo.find_by_id(_id(user))

        assert found is not None
        assert found.username == user.username

    async def it_returns_none_when_the_user_does_not_exist():
        assert await repo.find_by_id(PydanticObjectId()) is None


def describe_find_username_by_id():
    async def it_returns_the_username():
        user = await _user(username="find_username_target")

        assert await repo.find_username_by_id(_id(user)) == "find_username_target"

    async def it_returns_none_when_the_user_does_not_exist():
        assert await repo.find_username_by_id(PydanticObjectId()) is None


def describe_find_usernames_by_ids():
    async def it_maps_ids_to_usernames():
        alice = await _user(username="alice_lookup")
        bob = await _user(username="bob_lookup")

        result = await repo.find_usernames_by_ids([_id(alice), _id(bob)])

        assert result == {_id(alice): "alice_lookup", _id(bob): "bob_lookup"}

    async def it_returns_an_empty_dict_for_an_empty_list():
        assert await repo.find_usernames_by_ids([]) == {}


def describe_find_by_username():
    async def it_finds_a_user_by_username():
        await _user(username="find_by_username")

        found = await repo.find_by_username("find_by_username")

        assert found is not None
        assert found.username == "find_by_username"

    async def it_returns_none_when_no_user_matches():
        assert await repo.find_by_username("no_such_user") is None


def describe_find_id_by_username():
    async def it_resolves_the_id():
        user = await _user(username="resolve_id")

        assert await repo.find_id_by_username("resolve_id") == _id(user)

    async def it_returns_none_when_no_user_matches():
        assert await repo.find_id_by_username("no_such_user") is None


def describe_find_by_email():
    async def it_finds_a_user_by_email():
        await _user(email="find-by-email@example.com")

        found = await repo.find_by_email("find-by-email@example.com")

        assert found is not None
        assert found.email == "find-by-email@example.com"

    async def it_returns_none_when_no_user_matches():
        assert await repo.find_by_email("no-such-user@example.com") is None


def describe_find_id_by_linked_provider():
    async def it_finds_a_user_by_their_linked_provider_identity():
        user = await _user(
            username="linked_provider_user",
            linked_providers=[LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="google-ext-id")],
        )

        found_id = await repo.find_id_by_linked_provider(AuthProviderName.GOOGLE, "google-ext-id")

        assert found_id == _id(user)

    async def it_returns_none_when_no_user_matches():
        assert await repo.find_id_by_linked_provider(AuthProviderName.GOOGLE, "missing-ext-id") is None


def describe_find_refresh_tokens_by_id():
    async def it_returns_the_refresh_tokens():
        user = await _user(refresh_tokens=["token-a", "token-b"])

        assert await repo.find_refresh_tokens_by_id(_id(user)) == ["token-a", "token-b"]

    async def it_returns_none_when_the_user_does_not_exist():
        assert await repo.find_refresh_tokens_by_id(PydanticObjectId()) is None


def describe_exists_by_username():
    async def it_returns_true_when_the_username_exists():
        await _user(username="exists_username")

        assert await repo.exists_by_username("exists_username") is True

    async def it_returns_false_when_the_username_does_not_exist():
        assert await repo.exists_by_username("missing_username") is False


def describe_exists_by_email():
    async def it_returns_true_when_the_email_exists():
        await _user(email="exists-email@example.com")

        assert await repo.exists_by_email("exists-email@example.com") is True

    async def it_returns_false_when_the_email_does_not_exist():
        assert await repo.exists_by_email("missing-email@example.com") is False


def describe_save():
    async def it_persists_changes_to_an_existing_user():
        user = await _user()

        user.name = "Updated Name"
        await repo.save(user)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.name == "Updated Name"


def describe_increment_referral_count_by_username():
    async def it_increments_the_referral_count():
        user = await _user(username="referrer", referral_count=1)

        await repo.increment_referral_count_by_username("referrer")

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.referral_count == 2


def describe_push_read_book_by_id():
    async def it_appends_a_read_book():
        user = await _user()
        book_id = PydanticObjectId()

        await repo.push_read_book_by_id(_id(user), ReadBook(id=book_id, read_at=datetime.now(UTC)))

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert [b.id for b in found.books_read] == [book_id]


def describe_push_refresh_token_by_id():
    async def it_appends_a_refresh_token():
        user = await _user()

        await repo.push_refresh_token_by_id(_id(user), "some-refresh-token")

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.refresh_tokens == ["some-refresh-token"]


def describe_pull_refresh_token_by_id():
    async def it_removes_a_refresh_token():
        user = await _user(refresh_tokens=["token-a", "token-b"])

        await repo.pull_refresh_token_by_id(_id(user), "token-a")

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.refresh_tokens == ["token-b"]


def describe_add_linked_provider():
    async def it_appends_a_linked_provider():
        user = await _user()
        entry = LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="new-google-id")

        await repo.add_linked_provider(_id(user), entry)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert [(p.provider, p.external_id) for p in found.linked_providers] == [
            (AuthProviderName.GOOGLE, "new-google-id")
        ]


def describe_remove_linked_provider():
    async def it_removes_a_linked_provider():
        user = await _user(
            linked_providers=[LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="remove-me")]
        )

        await repo.remove_linked_provider(_id(user), AuthProviderName.GOOGLE)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.linked_providers == []
