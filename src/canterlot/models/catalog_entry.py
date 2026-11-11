from datetime import UTC, datetime
from typing import ClassVar

from beanie import Link
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from canterlot.hoodie import Entity

from .book import BookModel
from .club import ClubModel
from .user import UserModel


class CatalogEntryModel(Entity):
    club: Link[ClubModel]
    book: Link[BookModel]
    suggested_by: Link[UserModel]
    suggested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "catalog_entries"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("club.$id", ASCENDING), ("book.$id", ASCENDING)], unique=True, name="unique_club_book_idx"),
            IndexModel([("club.$id", ASCENDING), ("suggested_at", DESCENDING)], name="club_suggested_at_idx"),
        ]
