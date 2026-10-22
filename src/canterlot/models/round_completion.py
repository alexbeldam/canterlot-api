from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from beanie import PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from canterlot.hoodie import Entity


@dataclass
class CompletionResult:
    is_new: bool
    round_concluded: bool


class RoundCompletionModel(Entity):
    club_id: PydanticObjectId
    round_id: PydanticObjectId
    book_id: PydanticObjectId
    user_id: PydanticObjectId
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "round_completions"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel(
                [("round_id", ASCENDING), ("user_id", ASCENDING)],
                unique=True,
                name="unique_round_user_completion_idx",
            ),
            IndexModel([("club_id", ASCENDING), ("book_id", ASCENDING)], name="club_book_completion_idx"),
        ]
