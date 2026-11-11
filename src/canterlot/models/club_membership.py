from datetime import datetime
from typing import ClassVar

from beanie import Link
from pymongo import ASCENDING, IndexModel

from canterlot.hoodie import Entity
from canterlot.types import MembershipStatus

from .club import ClubModel
from .user import UserModel


class ClubMembershipModel(Entity):
    club: Link[ClubModel]
    user: Link[UserModel]
    status: MembershipStatus
    joined_at: datetime | None = None
    requested_at: datetime | None = None

    class Settings:
        name = "club_memberships"
        indexes: ClassVar[list[IndexModel]] = [
            IndexModel([("club.$id", ASCENDING), ("user.$id", ASCENDING)], unique=True, name="unique_club_user_idx"),
            IndexModel([("user.$id", ASCENDING)], name="user_membership_idx"),
        ]
