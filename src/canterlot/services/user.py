from beanie import PydanticObjectId

from canterlot.models.book import ReadBook
from canterlot.repositories.interfaces import UserRepository
from canterlot.utils import get_logger

logger = get_logger(__name__)


class UserService:
    def __init__(self, user_repo: UserRepository):
        self.__user_repo = user_repo

    async def mark_book_read(self, user_id: PydanticObjectId, book_id: PydanticObjectId) -> None:
        log = logger.bind(user_id=str(user_id), book_id=str(book_id))
        log.info("Marking book as read for user")

        await self.__user_repo.push_read_book_by_id(user_id=user_id, read_book=ReadBook(id=book_id))

        log.info("Book marked as read successfully")
