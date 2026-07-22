import re
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from beanie import PydanticObjectId

from canterlot.exceptions import CodeExpiredError, InvalidCodeError
from canterlot.models.verification import VerificationCodeModel
from canterlot.services.verification import VerificationService
from canterlot.types import VerificationScope


@pytest.fixture
def service(verification_repo):
    return VerificationService(repo=verification_repo)


@pytest.fixture
def sample_user_id():
    return PydanticObjectId()


def describe_create_code():

    async def it_generates_and_saves_a_secure_verification_code(service, verification_repo, sample_user_id):
        mock_model = MagicMock(spec=VerificationCodeModel)

        with (
            patch("canterlot.services.verification.generate_secure_alphanumeric_code", return_value="CODE4567"),
            patch("canterlot.models.verification.VerificationCodeModel.create", return_value=mock_model),
        ):
            plaintext = await service.create_code(sample_user_id, VerificationScope.EMAIL)

            assert plaintext == "CODE4567"
            verification_repo.create_and_invalidate_previous.assert_awaited_once_with(mock_model)


def describe_validate_code():

    async def it_raises_invalid_code_error_if_no_matching_active_code_exists(
        service, verification_repo, sample_user_id
    ):
        verification_repo.find_active_code.return_value = None

        with pytest.raises(
            InvalidCodeError,
            match="The verification code provided is incorrect or has already been used",
        ):
            await service.validate_code("WRONGCOD", sample_user_id, VerificationScope.EMAIL)

    async def it_raises_code_expired_error_if_code_lifetime_has_elapsed(service, verification_repo, sample_user_id):
        mock_model = MagicMock(spec=VerificationCodeModel)
        mock_model.id = PydanticObjectId()
        mock_model.expires_at = datetime.now(UTC) - timedelta(minutes=5)
        verification_repo.find_active_code.return_value = mock_model

        expected_msg = re.escape("This verification code has expired. Please request a new one")
        with pytest.raises(CodeExpiredError, match=expected_msg):
            await service.validate_code("EXPIRED4", sample_user_id, VerificationScope.EMAIL)

    async def it_successfully_validates_and_deactivates_an_active_valid_code(
        service,
        verification_repo,
        sample_user_id,
    ):
        mock_model = MagicMock(spec=VerificationCodeModel)
        mock_model.id = PydanticObjectId()
        mock_model.expires_at = datetime.now(UTC) + timedelta(minutes=15)
        verification_repo.find_active_code.return_value = mock_model

        await service.validate_code("VALIDCOD", sample_user_id, VerificationScope.EMAIL)

        verification_repo.deactivate_code_by_id.assert_awaited_once_with(mock_model.id)
