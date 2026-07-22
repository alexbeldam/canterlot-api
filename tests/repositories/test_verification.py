import pytest
from beanie import PydanticObjectId
from pydantic import SecretStr

from canterlot.factories import VerificationCodeFactory
from canterlot.models.verification import VerificationCodeModel
from canterlot.repositories.beanie.verification import BeanieVerificationRepository
from canterlot.types import VerificationScope
from canterlot.utils import generate_secure_code

pytestmark = pytest.mark.asyncio(loop_scope="session")

repo = BeanieVerificationRepository()


def _id(model: VerificationCodeModel) -> PydanticObjectId:
    return PydanticObjectId(model.id)


async def _create_code_model(
    user_id: PydanticObjectId,
    scope: VerificationScope,
    is_active: bool = True,
    plaintext_code: str | None = None,
    attempts: int = 0,
) -> tuple[VerificationCodeModel, SecretStr]:
    code = SecretStr(plaintext_code) if plaintext_code is not None else generate_secure_code()
    code_hash = VerificationCodeModel.hash_code(code, user_id)

    model = await VerificationCodeFactory.create_async(
        user_id=user_id,
        code_hash=code_hash,
        scope=scope,
        is_active=is_active,
        attempts=attempts,
    )
    return model, code


def describe_create_and_invalidate_previous():

    async def it_saves_new_code_and_deactivates_older_active_codes_in_same_scope():
        user_id = PydanticObjectId()

        old_active, _ = await _create_code_model(user_id, VerificationScope.EMAIL, is_active=True)
        old_inactive, _ = await _create_code_model(user_id, VerificationScope.EMAIL, is_active=False)
        different_scope, _ = await _create_code_model(user_id, VerificationScope.PASSWORD_RESET, is_active=True)

        new_code = generate_secure_code()
        new_model = VerificationCodeModel.create(new_code, user_id, VerificationScope.EMAIL)

        saved = await repo.create_and_invalidate_previous(new_model)

        assert saved.is_active is True

        check_old_active = await VerificationCodeModel.get(_id(old_active))
        assert check_old_active is not None
        assert check_old_active.is_active is False

        check_old_inactive = await VerificationCodeModel.get(_id(old_inactive))
        assert check_old_inactive is not None
        assert check_old_inactive.is_active is False

        check_diff_scope = await VerificationCodeModel.get(_id(different_scope))
        assert check_diff_scope is not None
        assert check_diff_scope.is_active is True


def describe_find_active_code():

    async def it_finds_an_active_code_by_matching_parameters():
        user_id = PydanticObjectId()
        _, plaintext = await _create_code_model(user_id, VerificationScope.EMAIL, is_active=True)

        expected_hash = VerificationCodeModel.hash_code(plaintext, user_id)

        found = await repo.find_active_code(user_id, expected_hash, VerificationScope.EMAIL)

        assert found is not None
        assert found.is_active is True

    async def it_returns_none_if_the_matching_code_is_inactive():
        user_id = PydanticObjectId()
        _, plaintext = await _create_code_model(user_id, VerificationScope.EMAIL, is_active=False)

        expected_hash = VerificationCodeModel.hash_code(plaintext, user_id)

        found = await repo.find_active_code(user_id, expected_hash, VerificationScope.EMAIL)
        assert found is None

    async def it_returns_none_if_scope_does_not_match():
        user_id = PydanticObjectId()
        _, plaintext = await _create_code_model(user_id, VerificationScope.EMAIL, is_active=True)

        expected_hash = VerificationCodeModel.hash_code(plaintext, user_id)

        found = await repo.find_active_code(user_id, expected_hash, VerificationScope.PASSWORD_RESET)
        assert found is None


def describe_deactivate_code_by_id():

    async def it_turns_an_active_code_inactive_by_its_identifier():
        user_id = PydanticObjectId()
        model, _ = await _create_code_model(user_id, VerificationScope.EMAIL, is_active=True)

        await repo.deactivate_code_by_id(_id(model))

        updated = await VerificationCodeModel.get(_id(model))
        assert updated is not None
        assert updated.is_active is False


def describe_increment_attempts_and_burn_if_exceeded():

    async def it_increments_attempts_without_deactivating_below_limit():
        user_id = PydanticObjectId()
        model, _ = await _create_code_model(user_id, VerificationScope.EMAIL, is_active=True)

        await repo.increment_attempts_and_burn_if_exceeded(user_id, VerificationScope.EMAIL, max_attempts=5)

        updated = await VerificationCodeModel.get(_id(model))
        assert updated is not None
        assert updated.attempts == 1
        assert updated.is_active is True

    async def it_deactivates_code_when_attempts_reach_max_limit():
        user_id = PydanticObjectId()
        model, _ = await _create_code_model(user_id, VerificationScope.EMAIL, is_active=True, attempts=4)

        await repo.increment_attempts_and_burn_if_exceeded(user_id, VerificationScope.EMAIL, max_attempts=5)

        updated = await VerificationCodeModel.get(_id(model))
        assert updated is not None
        assert updated.attempts == 5
        assert updated.is_active is False
