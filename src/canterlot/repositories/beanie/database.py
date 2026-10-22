from canterlot.models import UserModel
from canterlot.repositories import DatabaseRepository


class BeanieDatabaseRepository(DatabaseRepository):
    @property
    def name(self) -> str:
        return "mongodb"

    async def ping(self) -> None:
        await UserModel.get_pymongo_collection().database.command("ping")
