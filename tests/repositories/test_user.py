from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId
from pydantic import HttpUrl

from canterlot.emails import EmailCategory
from canterlot.factories import AvatarFactory, EmailPreferencesFactory, LinkedProviderFactory, UserFactory
from canterlot.models.book import ReadBook
from canterlot.models.user import UserModel
from canterlot.repositories.beanie.user import BeanieUserRepository
from canterlot.types import AuthProviderName

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieUserRepository()


def _id(user: UserModel) -> PydanticObjectId:
    return PydanticObjectId(user.id)


def describe_find_by_id():
    async def it_finds_a_user_by_id():
        user = await UserFactory.create_async()

        found = await repo.find_by_id(_id(user))

        assert found is not None
        assert found.username == user.username

    async def it_returns_none_when_the_user_does_not_exist():
        assert await repo.find_by_id(PydanticObjectId()) is None


def describe_find_username_by_id():
    async def it_returns_the_username():
        user = await UserFactory.create_async()

        assert await repo.find_username_by_id(_id(user)) == user.username

    async def it_returns_none_when_the_user_does_not_exist():
        assert await repo.find_username_by_id(PydanticObjectId()) is None


def describe_get_usernames_by_ids():
    async def it_maps_ids_to_usernames():
        alice = await UserFactory.create_async()
        bob = await UserFactory.create_async()

        result = await repo.find_usernames_by_ids([_id(alice), _id(bob)])

        assert result == {_id(alice): alice.username, _id(bob): bob.username}

    async def it_returns_an_empty_dict_for_an_empty_list():
        assert await repo.find_usernames_by_ids([]) == {}


def describe_find_by_username():
    async def it_finds_a_user_by_username():
        user = await UserFactory.create_async()

        found = await repo.find_by_username(user.username)

        assert found is not None
        assert found.username == user.username

    async def it_returns_none_when_no_user_matches():
        assert await repo.find_by_username(UserFactory.__faker__.user_name()) is None


def describe_find_id_by_username():
    async def it_resolves_the_id():
        user = await UserFactory.create_async()

        assert await repo.find_id_by_username(user.username) == _id(user)

    async def it_returns_none_when_no_user_matches():
        assert await repo.find_id_by_username(UserFactory.__faker__.user_name()) is None


def describe_find_by_email():
    async def it_finds_a_user_by_email():
        user = await UserFactory.create_async()

        found = await repo.find_by_email(user.email)

        assert found is not None
        assert found.email == user.email

    async def it_returns_none_when_no_user_matches():
        assert await repo.find_by_email(UserFactory.__faker__.email()) is None


def describe_find_id_by_linked_provider():
    async def it_finds_a_user_by_their_linked_provider_identity():
        provider = LinkedProviderFactory.build(provider=AuthProviderName.GOOGLE)
        user = await UserFactory.create_async(linked_providers=[provider])

        found_id = await repo.find_id_by_linked_provider(AuthProviderName.GOOGLE, provider.external_id)

        assert found_id == _id(user)

    async def it_returns_none_when_no_user_matches():
        assert await repo.find_id_by_linked_provider(AuthProviderName.GOOGLE, UserFactory.__faker__.uuid4()) is None


def describe_exists_by_username():
    async def it_returns_true_when_the_username_exists():
        user = await UserFactory.create_async()

        assert await repo.exists_by_username(user.username) is True

    async def it_returns_false_when_the_username_does_not_exist():
        assert await repo.exists_by_username(UserFactory.__faker__.user_name()) is False


def describe_exists_by_email():
    async def it_returns_true_when_the_email_exists():
        user = await UserFactory.create_async()

        assert await repo.exists_by_email(user.email) is True

    async def it_returns_false_when_the_email_does_not_exist():
        assert await repo.exists_by_email(UserFactory.__faker__.email()) is False


def describe_save():
    async def it_persists_changes_to_an_existing_user():
        user = await UserFactory.create_async()
        new_name = UserFactory.__faker__.name()

        user.name = new_name
        await repo.save(user)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.name == new_name


def describe_increment_referral_count_by_username():
    async def it_increments_the_referral_count():
        user = await UserFactory.create_async()
        initial_count = user.referral_count

        await repo.increment_referral_count_by_username(user.username)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.referral_count == initial_count + 1


def describe_push_read_book_by_id():
    async def it_appends_a_read_book():
        user = await UserFactory.create_async()
        book_id = PydanticObjectId()

        await repo.push_read_book_by_id(_id(user), ReadBook(id=book_id, read_at=datetime.now(UTC)))

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert [b.id for b in found.books_read] == [book_id]


def describe_push_refresh_token_by_id():
    async def it_appends_a_refresh_token():
        user = await UserFactory.create_async()
        token = UserFactory.__faker__.uuid4()

        await repo.push_refresh_token_by_id(_id(user), token)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.refresh_tokens == [token]


def describe_pull_refresh_token_by_id():
    async def it_removes_a_refresh_token_and_reports_it_was_present():
        token_a, token_b = UserFactory.__faker__.uuid4(), UserFactory.__faker__.uuid4()
        user = await UserFactory.create_async(refresh_tokens=[token_a, token_b])

        removed = await repo.pull_refresh_token_by_id(_id(user), token_a)

        assert removed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.refresh_tokens == [token_b]

    async def it_reports_false_when_the_token_is_not_in_the_array():
        token_a = UserFactory.__faker__.uuid4()
        user = await UserFactory.create_async(refresh_tokens=[token_a])

        removed = await repo.pull_refresh_token_by_id(_id(user), UserFactory.__faker__.uuid4())

        assert removed is False
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.refresh_tokens == [token_a]

    async def it_reports_false_for_a_nonexistent_user():
        removed = await repo.pull_refresh_token_by_id(PydanticObjectId(), UserFactory.__faker__.uuid4())

        assert removed is False


def describe_add_linked_provider():
    async def it_appends_a_linked_provider():
        user = await UserFactory.create_async()
        entry = LinkedProviderFactory.build(provider=AuthProviderName.GOOGLE)

        assert await repo.add_linked_provider(_id(user), entry) is True

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert [(p.provider, p.external_id) for p in found.linked_providers] == [
            (AuthProviderName.GOOGLE, entry.external_id)
        ]

    async def it_returns_false_when_another_user_already_claimed_the_identity():
        provider = LinkedProviderFactory.build(provider=AuthProviderName.GOOGLE)
        await UserFactory.create_async(linked_providers=[provider])
        challenger = await UserFactory.create_async()

        result = await repo.add_linked_provider(_id(challenger), provider)

        assert result is False
        found = await repo.find_by_id(_id(challenger))
        assert found is not None
        assert found.linked_providers == []


def describe_save_new_oauth_account():
    async def it_persists_a_brand_new_account():
        provider = LinkedProviderFactory.build(provider=AuthProviderName.GOOGLE)
        user = UserFactory.build(linked_providers=[provider])

        saved = await repo.save_new_oauth_account(user)

        assert saved is not None
        found = await repo.find_by_id(_id(saved))
        assert found is not None
        assert found.username == user.username

    async def it_returns_none_when_the_identity_is_already_claimed():
        provider = LinkedProviderFactory.build(provider=AuthProviderName.GOOGLE)
        await UserFactory.create_async(linked_providers=[provider])
        conflicting_user = UserFactory.build(linked_providers=[provider])

        assert await repo.save_new_oauth_account(conflicting_user) is None


def describe_remove_linked_provider():
    async def it_removes_a_linked_provider():
        provider = LinkedProviderFactory.build(provider=AuthProviderName.GOOGLE)
        user = await UserFactory.create_async(linked_providers=[provider])

        await repo.remove_linked_provider(_id(user), AuthProviderName.GOOGLE)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.linked_providers == []


def describe_update_profile():
    async def it_updates_both_fields():
        user = await UserFactory.create_async()
        new_name = UserFactory.__faker__.name()
        new_username = UserFactory.__faker__.user_name().replace(".", "_")

        changed = await repo.update_profile(_id(user), name=new_name, username=new_username)

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.name == new_name
        assert found.username == new_username

    async def it_updates_only_the_provided_field():
        user = await UserFactory.create_async()
        new_name = UserFactory.__faker__.name()

        changed = await repo.update_profile(_id(user), name=new_name)

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.name == new_name
        assert found.username == user.username

    async def it_returns_false_for_a_nonexistent_user():
        changed = await repo.update_profile(PydanticObjectId(), name=UserFactory.__faker__.name())

        assert changed is False


def describe_change_password():
    async def it_stores_the_hash_and_replaces_all_refresh_tokens():
        user = await UserFactory.create_async()
        old_token = UserFactory.__faker__.uuid4()
        new_token = UserFactory.__faker__.uuid4()
        new_password_hash = UserFactory.__faker__.sha256()

        await repo.push_refresh_token_by_id(_id(user), old_token)

        await repo.change_password(_id(user), new_password_hash, new_token)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.hashed_password == new_password_hash
        assert found.refresh_tokens == [new_token]


def describe_set_legal_acceptance():
    async def it_sets_all_five_fields():
        user = await UserFactory.create_async(
            accepted_terms_version=None,
            accepted_terms_at=None,
            accepted_privacy_version=None,
            accepted_privacy_at=None,
            profile_completed_at=None,
        )
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
        provider = LinkedProviderFactory.build(provider=AuthProviderName.GOOGLE)
        new_pic_url = HttpUrl(UserFactory.__faker__.image_url())
        user = await UserFactory.create_async(linked_providers=[provider])

        await repo.update_linked_provider_picture(_id(user), AuthProviderName.GOOGLE, new_pic_url)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert str(found.linked_providers[0].picture_url) == str(new_pic_url)

    async def it_is_a_no_op_for_a_nonexistent_user():
        new_pic_url = HttpUrl(UserFactory.__faker__.image_url())
        await repo.update_linked_provider_picture(PydanticObjectId(), AuthProviderName.GOOGLE, new_pic_url)


def describe_find_avatar_by_id():
    async def it_returns_the_avatar():
        avatar = AvatarFactory.build()
        user = await UserFactory.create_async(avatar=avatar)

        found_avatar = await repo.find_avatar_by_id(_id(user))

        assert found_avatar is not None
        assert found_avatar.source == avatar.source
        assert str(found_avatar.value) == str(avatar.value)

    async def it_returns_none_when_the_user_has_no_avatar_set():
        user = await UserFactory.create_async(avatar=None)

        assert await repo.find_avatar_by_id(_id(user)) is None

    async def it_returns_none_for_a_nonexistent_user():
        assert await repo.find_avatar_by_id(PydanticObjectId()) is None


def describe_set_avatar():
    async def it_sets_the_avatar_without_touching_the_generated_seed():
        user = await UserFactory.create_async()
        avatar = AvatarFactory.build()

        changed = await repo.set_avatar(_id(user), avatar)

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.avatar is not None
        assert found.avatar.source == avatar.source
        assert found.generated_avatar_seed == user.generated_avatar_seed

    async def it_returns_false_for_a_nonexistent_user():
        avatar = AvatarFactory.build()
        changed = await repo.set_avatar(PydanticObjectId(), avatar)

        assert changed is False


def describe_clear_avatar():
    async def it_clears_the_avatar():
        avatar = AvatarFactory.build()
        user = await UserFactory.create_async(avatar=avatar)

        changed = await repo.clear_avatar(_id(user))

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.avatar is None

    async def it_returns_false_for_a_nonexistent_user():
        assert await repo.clear_avatar(PydanticObjectId()) is False


def describe_set_generated_avatar_seed():
    async def it_updates_the_generated_seed():
        user = await UserFactory.create_async()
        new_seed = UserFactory.__faker__.uuid4()

        changed = await repo.set_generated_avatar_seed(_id(user), new_seed)

        assert changed is True
        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.generated_avatar_seed == new_seed

    async def it_returns_false_for_a_nonexistent_user():
        assert await repo.set_generated_avatar_seed(PydanticObjectId(), UserFactory.__faker__.uuid4()) is False


def describe_touch_last_seen():
    async def it_stamps_last_seen_at_for_a_user_who_was_never_seen_before():
        user = await UserFactory.create_async(last_seen_at=None)
        now = datetime.now(UTC)

        await repo.touch_last_seen(_id(user), now)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.last_seen_at is not None
        assert abs((found.last_seen_at.replace(tzinfo=UTC) - now).total_seconds()) < 5

    async def it_updates_last_seen_at_once_the_prior_stamp_is_more_than_a_day_old():
        stale = datetime.now(UTC) - timedelta(days=2)
        user = await UserFactory.create_async(last_seen_at=stale)
        now = datetime.now(UTC)

        await repo.touch_last_seen(_id(user), now)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.last_seen_at is not None
        assert abs((found.last_seen_at.replace(tzinfo=UTC) - now).total_seconds()) < 5

    async def it_does_not_overwrite_a_stamp_from_earlier_today():
        recent = datetime.now(UTC) - timedelta(hours=1)
        user = await UserFactory.create_async(last_seen_at=recent)

        await repo.touch_last_seen(_id(user), datetime.now(UTC))

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.last_seen_at is not None
        assert found.last_seen_at.timestamp() == pytest.approx(recent.timestamp(), abs=1e-3)

    async def it_is_a_no_op_for_a_nonexistent_user():
        await repo.touch_last_seen(PydanticObjectId(), datetime.now(UTC))


def describe_get_by_ids():
    async def it_returns_users_matching_provided_ids():
        alice = await UserFactory.create_async()
        bob = await UserFactory.create_async()

        result = await repo.get_by_ids([_id(alice), _id(bob)])

        assert len(result) == 2
        retrieved_ids = {_id(u) for u in result}
        assert _id(alice) in retrieved_ids
        assert _id(bob) in retrieved_ids

    async def it_returns_an_empty_list_when_input_ids_is_empty():
        assert await repo.get_by_ids([]) == []


def describe_find_email_preferences_by_email():
    async def it_returns_email_preferences_for_matching_email():
        email_prefs = EmailPreferencesFactory.build()
        user = await UserFactory.create_async(email_preferences=email_prefs)

        prefs = await repo.find_email_preferences_by_email(user.email)

        assert prefs is not None
        assert prefs.delivery_failed == email_prefs.delivery_failed

    async def it_returns_none_when_no_user_matches():
        assert await repo.find_email_preferences_by_email(UserFactory.__faker__.email()) is None


def describe_find_by_linked_provider():
    async def it_returns_user_model_for_matching_linked_provider():
        provider = LinkedProviderFactory.build()
        user = await UserFactory.create_async(linked_providers=[provider])

        found = await repo.find_by_linked_provider(provider.provider, provider.external_id)

        assert found is not None
        assert _id(found) == _id(user)

    async def it_returns_none_when_provider_identity_does_not_exist():
        assert await repo.find_by_linked_provider(AuthProviderName.GOOGLE, UserFactory.__faker__.uuid4()) is None


def describe_is_email_verified_by_id():
    async def it_returns_true_when_email_is_verified():
        email_prefs = EmailPreferencesFactory.build(verified_at=datetime.now(UTC))
        user = await UserFactory.create_async(email_preferences=email_prefs)

        assert await repo.is_email_verified_by_id(_id(user)) is True

    async def it_returns_false_when_email_is_not_verified():
        email_prefs = EmailPreferencesFactory.build(verified_at=None)
        user = await UserFactory.create_async(email_preferences=email_prefs)

        assert await repo.is_email_verified_by_id(_id(user)) is False


def describe_apply_global_suppression_by_email():
    async def it_flags_delivery_failed_and_suppresses_all_categories():
        user = await UserFactory.create_async()
        now = datetime.now(UTC)

        modified = await repo.apply_global_suppression_by_email(user.email, now)

        assert modified is True
        found = await repo.find_by_email(user.email)
        assert found is not None
        assert found.email_preferences.delivery_failed is True
        assert "transactional" in found.email_preferences.categories_system_suppressed
        assert "engagement" in found.email_preferences.categories_system_suppressed
        assert "promotional" in found.email_preferences.categories_system_suppressed


def describe_apply_spam_suppression_by_email():
    async def it_suppresses_engagement_and_promotional_categories():
        user = await UserFactory.create_async()
        now = datetime.now(UTC)

        modified = await repo.apply_spam_suppression_by_email(user.email, now)

        assert modified is True
        found = await repo.find_by_email(user.email)
        assert found is not None
        assert found.email_preferences.delivery_failed is True
        assert "engagement" in found.email_preferences.categories_system_suppressed
        assert "promotional" in found.email_preferences.categories_system_suppressed
        assert "transactional" not in found.email_preferences.categories_system_suppressed


def describe_set_delivery_failed_by_email():
    async def it_updates_the_delivery_failed_flag():
        user = await UserFactory.create_async()

        modified = await repo.set_delivery_failed_by_email(user.email, True)

        assert modified is True
        found = await repo.find_by_email(user.email)
        assert found is not None
        assert found.email_preferences.delivery_failed is True


def describe_opt_out_club_by_id():
    async def it_opts_out_from_a_specific_club():
        user = await UserFactory.create_async()
        club_id = PydanticObjectId()
        now = datetime.now(UTC)

        assert await repo.opt_out_club_by_id(_id(user), club_id, now) is True

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert club_id in found.email_preferences.clubs_opt_out

    async def it_returns_false_for_a_nonexistent_user():
        assert (
            await repo.opt_out_club_by_id(
                PydanticObjectId(),
                PydanticObjectId(),
                datetime.now(UTC),
            )
            is False
        )


def describe_opt_out_category_by_id():
    async def it_opts_out_from_a_specific_category():
        user = await UserFactory.create_async()
        now = datetime.now(UTC)

        assert await repo.opt_out_category_by_id(_id(user), EmailCategory.PROMOTIONAL, now) is True

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert EmailCategory.PROMOTIONAL.value in found.email_preferences.categories_opt_out

    async def it_returns_false_for_a_nonexistent_user():
        assert (
            await repo.opt_out_category_by_id(
                PydanticObjectId(),
                EmailCategory.PROMOTIONAL,
                datetime.now(UTC),
            )
            is False
        )


def describe_find_by_identifier():
    async def it_finds_by_email_identifier():
        user = await UserFactory.create_async()

        found = await repo.find_by_identifier(user.email)

        assert found is not None
        assert _id(found) == _id(user)

    async def it_finds_by_username_identifier():
        user = await UserFactory.create_async()

        found = await repo.find_by_identifier(user.username)

        assert found is not None
        assert _id(found) == _id(user)

    async def it_returns_none_when_identifier_matches_nothing():
        assert await repo.find_by_identifier(UserFactory.__faker__.email()) is None


def describe_find_id_by_identifier():
    async def it_finds_id_by_email_identifier():
        user = await UserFactory.create_async()

        found_id = await repo.find_id_by_identifier(user.email)

        assert found_id == _id(user)

    async def it_finds_id_by_username_identifier():
        user = await UserFactory.create_async()

        found_id = await repo.find_id_by_identifier(user.username)

        assert found_id == _id(user)

    async def it_returns_none_when_identifier_matches_nothing():
        assert await repo.find_id_by_identifier(UserFactory.__faker__.email()) is None


def describe_mark_email_as_verified():
    async def it_marks_email_as_verified_with_given_timestamp():
        email_prefs = EmailPreferencesFactory.build(verified_at=None)
        user = await UserFactory.create_async(email_preferences=email_prefs)

        now = datetime.now(UTC)
        await repo.mark_email_as_verified(_id(user), now)

        found = await repo.find_by_id(_id(user))
        assert found is not None
        assert found.email_preferences.verified_at is not None
        assert abs((found.email_preferences.verified_at.replace(tzinfo=UTC) - now).total_seconds()) < 5
