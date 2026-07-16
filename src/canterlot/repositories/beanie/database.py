from pymongo.errors import PyMongoError

from canterlot.models import UserModel
from canterlot.repositories import DatabaseRepository


class BeanieDatabaseRepository(DatabaseRepository):
    async def ping(self) -> bool:
        try:
            await UserModel.get_pymongo_collection().database.command("ping")
            return True
        except PyMongoError:
            return False
