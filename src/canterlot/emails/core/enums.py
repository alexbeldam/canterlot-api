from enum import StrEnum


class EmailPriority(StrEnum):
    HIGH = "high"
    DEFAULT = "default"
    LOW = "low"


class EmailCategory(StrEnum):
    TRANSACTIONAL = "transactional"
    ENGAGEMENT = "engagement"
    PROMOTIONAL = "promotional"


class SubBrand(StrEnum):
    CELESTIA = "celestia"
    SPIKE = "spike"
    LUNA = "luna"

    @property
    def sender(self) -> str:
        return f"{self.value.title()} · Canterlot <{self.value}@noreply.canterlot.com.br>"
