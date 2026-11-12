from beanie import Link

from canterlot.hoodie import Entity
from tests.hoodie.cyclic_parent import CyclicParent


class CyclicChild(Entity):
    parent: Link[CyclicParent]

    class Settings:
        name = "hoodie_test_cyclic_children"
