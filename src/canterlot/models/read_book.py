from datetime import UTC, datetime
from typing import ClassVar

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel


class RatingStats(BaseModel):
    average_rating: float | None = None
    rating_count: int = 0


class ReadBookModel(Document):
    user_id: PydanticObjectId
    book_id: PydanticObjectId
    rating: float | None = Field(default=None, ge=0.5, le=5.0, multiple_of=0.5)
    read_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "read_books"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel(
                [("user_id", ASCENDING), ("book_id", ASCENDING)],
                unique=True,
                name="unique_user_book_idx",
            )
        ]
