from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from beanie import BackLink, Indexed, PydanticObjectId
from pydantic import Field

from canterlot.hoodie import Entity, searchable
from canterlot.types import ClubNameStr, ClubSlugStr, JoinPolicy, LanguageStr

if TYPE_CHECKING:
    from .catalog_entry import CatalogEntryModel
    from .club_membership import ClubMembershipModel
    from .invite import InviteModel


class ClubModel(Entity):
    name: ClubNameStr = searchable()
    description: str | None = None
    slug: Annotated[ClubSlugStr, Indexed(unique=True)] = searchable()
    join_policy: JoinPolicy = JoinPolicy.PUBLIC
    allow_suggestions: bool = True
    preferred_languages: list[LanguageStr] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ownership_transferred_at: datetime | None = None
    protected_former_owner_id: PydanticObjectId | None = None
    memberships: list[BackLink["ClubMembershipModel"]] = Field(
        default_factory=list,
        json_schema_extra={"original_field": "club"},
        exclude=True,
    )
    catalog_entries: list[BackLink["CatalogEntryModel"]] = Field(
        default_factory=list,
        json_schema_extra={"original_field": "club"},
        exclude=True,
    )
    invites: list[BackLink["InviteModel"]] = Field(
        default_factory=list,
        json_schema_extra={"original_field": "club"},
        exclude=True,
    )

    class Settings:
        name = "clubs"
        search_index = "clubs_search"
