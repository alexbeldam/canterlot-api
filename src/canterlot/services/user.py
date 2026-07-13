from beanie import PydanticObjectId

from canterlot.exceptions import InvalidCredentialsError, UsernameAlreadyExistsError
from canterlot.models.book import ReadBook
from canterlot.models.user import PersonNameStr, UserModel, UsernameStr
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

    async def update_profile(
        self,
        user_id: PydanticObjectId,
        name: PersonNameStr | None,
        username: UsernameStr | None,
    ) -> UserModel:
        log = logger.bind(user_id=str(user_id))
        log.info("Attempting profile update")

        user = await self.__user_repo.find_by_id(user_id)
        if not user:
            log.warn("Profile update aborted: authenticated user profile record no longer exists")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        if username is not None and username != user.username and await self.__user_repo.exists_by_username(username):
            log.warn("Profile update rejected: username conflict", reason="username_taken")
            raise UsernameAlreadyExistsError(f"Username '{username}' is already taken.")

        changed = await self.__user_repo.update_profile(user_id, name=name, username=username)
        if not changed:
            log.warn("Profile update rejected: user no longer exists at write time")
            raise InvalidCredentialsError("Authenticated user profile record no longer exists.")

        if name is not None:
            user.name = name
        if username is not None:
            user.username = username

        log.info("Profile updated successfully")
        return user
