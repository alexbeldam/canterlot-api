from typing import TYPE_CHECKING

from beanie import BackLink
from pydantic import Field

from canterlot.hoodie import Entity

if TYPE_CHECKING:
    from tests.hoodie.cyclic_child import CyclicChild


class CyclicParent(Entity):
    label: str = "default"
    children: list[BackLink["CyclicChild"]] = Field(
        default_factory=list,
        json_schema_extra={"original_field": "parent"},
        exclude=True,
    )

    class Settings:
        name = "hoodie_test_cyclic_parents"
