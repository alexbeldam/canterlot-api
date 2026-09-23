from datetime import UTC, datetime
from typing import ClassVar

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel


class CatalogEntryModel(Document):
    club_id: PydanticObjectId
    book_id: PydanticObjectId
    suggested_by: PydanticObjectId
    suggested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "catalog_entries"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("club_id", ASCENDING), ("book_id", ASCENDING)], unique=True, name="unique_club_book_idx"),
            IndexModel([("club_id", ASCENDING), ("suggested_at", DESCENDING)], name="club_suggested_at_idx"),
        ]
