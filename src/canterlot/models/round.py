from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

from beanie import BackLink, Link, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from canterlot.hoodie import Entity
from canterlot.types import DeadlineUnit, RoundResolutionMethod, RoundSelectionMode, RoundStatus

from .book import BookModel
from .club import ClubModel
from .user import UserModel

if TYPE_CHECKING:
    from .round_completion import RoundCompletionModel

ACTIVE_ROUND_STATUSES = (RoundStatus.SETUP, RoundStatus.VOTING, RoundStatus.DECIDED)


class DeadlineDuration(BaseModel):
    value: int = Field(ge=1, le=52)
    unit: DeadlineUnit


class RoundModel(Entity):
    club: Link[ClubModel]
    selection_mode: RoundSelectionMode
    status: RoundStatus
    resolution_method: RoundResolutionMethod | None = None
    candidate_pool: list[Link[BookModel]] = Field(default_factory=list)
    book: Link[BookModel] | None = None
    deadline_duration: DeadlineDuration | None = None
    deadline: datetime | None = None
    started_by: Link[UserModel]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
    last_completed_by: PydanticObjectId | None = None
    last_completed_at: datetime | None = None
    completions: list[BackLink["RoundCompletionModel"]] = Field(
        default_factory=list,
        json_schema_extra={"original_field": "round"},
        exclude=True,
    )

    class Settings:
        name = "reading_rounds"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("club.$id", ASCENDING), ("status", ASCENDING)], name="club_active_round_idx"),
        ]
