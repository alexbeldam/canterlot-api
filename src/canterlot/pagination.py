from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from fastapi import Query
from pydantic import BaseModel, Field, computed_field


class SortDirection(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


@dataclass
class PageRequest:
    page: int = Query(default=1, ge=1)
    limit: int = Query(default=20, ge=1, le=100)
    sort_by: str | None = Query(default=None, examples=["created_at"])
    sort_direction: SortDirection = Query(default=SortDirection.DESC)  # noqa: RUF009 -- FastAPI sentinel, not mutable state


class Page[ItemT](BaseModel):
    items: list[ItemT]
    total_items: int = Field(ge=0)
    current_page: int = Field(ge=1)
    page_size: int = Field(ge=1)

    @classmethod
    def of(cls, items: list[ItemT], page: int, limit: int) -> "Page[ItemT]":
        start = (page - 1) * limit
        end = start + limit

        return cls(items=items[start:end], total_items=len(items), current_page=page, page_size=limit)

    def map[U](self, fn: Callable[[ItemT], U]) -> "Page[U]":
        return Page(
            items=[fn(item) for item in self.items],
            total_items=self.total_items,
            current_page=self.current_page,
            page_size=self.page_size,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_pages(self) -> int:
        return -(-self.total_items // self.page_size)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_next(self) -> bool:
        return self.current_page < self.total_pages

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_previous(self) -> bool:
        return self.current_page > 1
