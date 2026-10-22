from datetime import UTC, datetime
from typing import ClassVar

from beanie import PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from canterlot.hoodie import Entity
from canterlot.types import DeadlineUnit, RoundResolutionMethod, RoundSelectionMode, RoundStatus

ACTIVE_ROUND_STATUSES = (RoundStatus.SETUP, RoundStatus.VOTING, RoundStatus.DECIDED)


class DeadlineDuration(BaseModel):
    value: int = Field(ge=1, le=52)
    unit: DeadlineUnit


class CandidatePoolEntry(BaseModel):
    book_id: PydanticObjectId


class RoundModel(Entity):
    club_id: PydanticObjectId
    selection_mode: RoundSelectionMode
    status: RoundStatus
    resolution_method: RoundResolutionMethod | None = None
    candidate_pool: list[CandidatePoolEntry] = Field(default_factory=list)
    book_id: PydanticObjectId | None = None
    deadline_duration: DeadlineDuration | None = None
    deadline: datetime | None = None
    started_by: PydanticObjectId
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
    last_completed_by: PydanticObjectId | None = None
    last_completed_at: datetime | None = None

    class Settings:
        name = "reading_rounds"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("club_id", ASCENDING), ("status", ASCENDING)], name="club_active_round_idx"),
        ]
