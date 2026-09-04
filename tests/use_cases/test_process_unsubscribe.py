from unittest.mock import AsyncMock

import pytest
from beanie import PydanticObjectId

from canterlot.use_cases.process_unsubscribe import ProcessUnsubscribeUseCase
from canterlot.utils.security import UnsubscribeScope, encode_club_unsubscribe_token

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_CLUB_ID = PydanticObjectId("507f1f77bcf86cd799439012")


@pytest.fixture
def use_case(user_service: AsyncMock) -> ProcessUnsubscribeUseCase:
    return ProcessUnsubscribeUseCase(user_service)


def describe_process_unsubscribe_use_case():
    async def it_decodes_the_token_and_delegates_to_the_user_service(
        use_case: ProcessUnsubscribeUseCase,
        user_service: AsyncMock,
    ):
        token = encode_club_unsubscribe_token(SOME_USER_ID, SOME_CLUB_ID)
        user_service.process_unsubscribe.return_value = UnsubscribeScope.CLUB

        result = await use_case.execute(token)

        assert result == UnsubscribeScope.CLUB

        user_service.process_unsubscribe.assert_awaited_once()
        token_data = user_service.process_unsubscribe.call_args.args[0]
        assert token_data.scope == UnsubscribeScope.CLUB
        assert token_data.user_id == SOME_USER_ID
        assert token_data.club_id == SOME_CLUB_ID
