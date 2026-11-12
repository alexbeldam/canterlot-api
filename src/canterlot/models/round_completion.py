from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from beanie import Link
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from canterlot.hoodie import Entity

from .book import BookModel
from .club import ClubModel
from .round import RoundModel
from .user import UserModel


@dataclass
class CompletionResult:
    is_new: bool
    round_concluded: bool


class RoundCompletionModel(Entity):
    club: Link[ClubModel]
    round: Link[RoundModel]
    book: Link[BookModel]
    user: Link[UserModel]
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "round_completions"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel(
                [("round.$id", ASCENDING), ("user.$id", ASCENDING)],
                unique=True,
                name="unique_round_user_completion_idx",
            ),
            IndexModel([("club.$id", ASCENDING), ("book.$id", ASCENDING)], name="club_book_completion_idx"),
        ]
