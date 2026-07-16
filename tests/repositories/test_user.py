from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId
from pydantic import HttpUrl

from canterlot.models.book import ReadBook
from canterlot.models.enums import AuthProviderName
from canterlot.models.user import AvatarSchema, LinkedProviderSchema, UserModel
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
    async def it_removes_a_refresh_token_and_reports_it_was_present():
        user = await _user(refresh_tokens=["token-a", "token-b"])

        removed = await repo.pull_refresh_token_by_id(_id(user), "token-a")

        assert removed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.refresh_tokens == ["token-b"]

    async def it_reports_false_when_the_token_is_not_in_the_array():
        user = await _user(refresh_tokens=["token-a"])

        removed = await repo.pull_refresh_token_by_id(_id(user), "never-issued-token")

        assert removed is False
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.refresh_tokens == ["token-a"]

    async def it_reports_false_for_a_nonexistent_user():
        removed = await repo.pull_refresh_token_by_id(PydanticObjectId(), "some-token")

        assert removed is False


def describe_add_linked_provider():
    async def it_appends_a_linked_provider():
        user = await _user()
        entry = LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="new-google-id")

        assert await repo.add_linked_provider(_id(user), entry) is True

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert [(p.provider, p.external_id) for p in found.linked_providers] == [
            (AuthProviderName.GOOGLE, "new-google-id")
        ]

    async def it_returns_false_when_another_user_already_claimed_the_identity():
        await _user(linked_providers=[LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="claimed-id")])
        challenger = await _user()

        result = await repo.add_linked_provider(
            _id(challenger),
            LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="claimed-id"),
        )

        assert result is False
        found = await repo.find_by_id(_id(challenger))
        assert found is not None
        assert found.linked_providers == []


def describe_save_new_oauth_account():
    async def it_persists_a_brand_new_account():
        user = UserModel(
            name="Rarity",
            username="rarity_oauth_account",
            email="rarity-oauth@example.com",
            linked_providers=[LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="rarity-google-id")],
        )

        saved = await repo.save_new_oauth_account(user)

        assert saved is not None
        found = await repo.find_by_id(_id(saved))
        assert found is not None
        assert found.username == "rarity_oauth_account"

    async def it_returns_none_when_the_identity_is_already_claimed():
        await _user(
            linked_providers=[LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="already-claimed")]
        )
        conflicting_user = UserModel(
            name="Applejack",
            username="applejack_oauth_conflict",
            email="applejack-oauth-conflict@example.com",
            linked_providers=[LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="already-claimed")],
        )

        assert await repo.save_new_oauth_account(conflicting_user) is None


def describe_remove_linked_provider():
    async def it_removes_a_linked_provider():
        user = await _user(
            linked_providers=[LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="remove-me")]
        )

        await repo.remove_linked_provider(_id(user), AuthProviderName.GOOGLE)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.linked_providers == []


def describe_update_profile():
    async def it_updates_both_fields():
        user = await _user(name="Original Name")

        changed = await repo.update_profile(_id(user), name="New Name", username="new_profile_username")

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.name == "New Name"
        assert found.username == "new_profile_username"

    async def it_updates_only_the_provided_field():
        user = await _user(name="Original Name")

        changed = await repo.update_profile(_id(user), name="Updated Name Only")

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.name == "Updated Name Only"
        assert found.username == user.username

    async def it_returns_false_for_a_nonexistent_user():
        changed = await repo.update_profile(PydanticObjectId(), name="Nobody")

        assert changed is False


def describe_change_password():
    async def it_stores_the_hash_and_replaces_all_refresh_tokens():
        user = await _user()
        await repo.push_refresh_token_by_id(_id(user), "old-token-1")
        await repo.push_refresh_token_by_id(_id(user), "old-token-2")

        await repo.change_password(_id(user), "new-hashed-password", "brand-new-refresh-token")

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.hashed_password == "new-hashed-password"
        assert found.refresh_tokens == ["brand-new-refresh-token"]


def describe_set_legal_acceptance():
    async def it_sets_all_five_fields():
        user = await _user()
        now = datetime.now(UTC)

        changed = await repo.set_legal_acceptance(
            _id(user),
            terms_version=1,
            terms_at=now,
            privacy_version=1,
            privacy_at=now,
            profile_completed_at=now,
        )

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.accepted_terms_version == 1
        assert found.accepted_privacy_version == 1
        assert found.profile_completed_at is not None

    async def it_returns_false_for_a_nonexistent_user():
        now = datetime.now(UTC)

        changed = await repo.set_legal_acceptance(
            PydanticObjectId(),
            terms_version=1,
            terms_at=now,
            privacy_version=1,
            privacy_at=now,
            profile_completed_at=now,
        )

        assert changed is False


def describe_update_linked_provider_picture():
    async def it_updates_the_matching_providers_picture_url():
        user = await _user(
            linked_providers=[LinkedProviderSchema(provider=AuthProviderName.GOOGLE, external_id="pic-update-id")]
        )

        await repo.update_linked_provider_picture(
            _id(user), AuthProviderName.GOOGLE, HttpUrl("https://example.com/new.jpg")
        )

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert str(found.linked_providers[0].picture_url) == "https://example.com/new.jpg"

    async def it_is_a_no_op_for_a_nonexistent_user():
        await repo.update_linked_provider_picture(
            PydanticObjectId(), AuthProviderName.GOOGLE, HttpUrl("https://example.com/new.jpg")
        )


def describe_find_avatar_by_id():
    async def it_returns_the_avatar():
        user = await _user(
            avatar=AvatarSchema(source=AuthProviderName.GRAVATAR, value=HttpUrl("https://gravatar.com/avatar/somehash"))
        )

        avatar = await repo.find_avatar_by_id(_id(user))

        assert avatar is not None
        assert avatar.source == AuthProviderName.GRAVATAR
        assert str(avatar.value) == "https://gravatar.com/avatar/somehash"

    async def it_returns_none_when_the_user_has_no_avatar_set():
        user = await _user()

        assert await repo.find_avatar_by_id(_id(user)) is None

    async def it_returns_none_for_a_nonexistent_user():
        assert await repo.find_avatar_by_id(PydanticObjectId()) is None


def describe_set_avatar():
    async def it_sets_the_avatar_without_touching_the_generated_seed():
        user = await _user(generated_avatar_seed="original-seed")

        changed = await repo.set_avatar(
            _id(user),
            AvatarSchema(source=AuthProviderName.GRAVATAR, value=HttpUrl("https://gravatar.com/avatar/somehash")),
        )

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.avatar is not None
        assert found.avatar.source == AuthProviderName.GRAVATAR
        assert found.generated_avatar_seed == "original-seed"

    async def it_returns_false_for_a_nonexistent_user():
        changed = await repo.set_avatar(
            PydanticObjectId(),
            AvatarSchema(source=AuthProviderName.GRAVATAR, value=HttpUrl("https://gravatar.com/avatar/x")),
        )

        assert changed is False


def describe_clear_avatar():
    async def it_clears_the_avatar():
        user = await _user(
            avatar=AvatarSchema(source=AuthProviderName.GOOGLE, value=HttpUrl("https://example.com/pic.jpg"))
        )

        changed = await repo.clear_avatar(_id(user))

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.avatar is None

    async def it_returns_false_for_a_nonexistent_user():
        assert await repo.clear_avatar(PydanticObjectId()) is False


def describe_set_generated_avatar_seed():
    async def it_updates_the_generated_seed():
        user = await _user(generated_avatar_seed="original-seed")

        changed = await repo.set_generated_avatar_seed(_id(user), "new-seed")

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.generated_avatar_seed == "new-seed"

    async def it_returns_false_for_a_nonexistent_user():
        assert await repo.set_generated_avatar_seed(PydanticObjectId(), "new-seed") is False
