from unittest.mock import AsyncMock

from beanie import PydanticObjectId

from canterlot.models.book import ReadBook
from canterlot.services.user import UserService

SOME_USER_ID = PydanticObjectId("507f1f77bcf86cd799439011")
SOME_BOOK_ID = PydanticObjectId("507f1f77bcf86cd799439012")


def describe_marking_a_book_as_read():
    async def it_appends_the_book_to_the_users_reading_history(user_repo: AsyncMock):
        service = UserService(user_repo)

        await service.mark_book_read(user_id=SOME_USER_ID, book_id=SOME_BOOK_ID)

        user_repo.push_read_book_by_id.assert_awaited_once()
        call_kwargs = user_repo.push_read_book_by_id.call_args.kwargs
        assert call_kwargs["user_id"] == SOME_USER_ID
        assert isinstance(call_kwargs["read_book"], ReadBook)
        assert call_kwargs["read_book"].id == SOME_BOOK_ID
