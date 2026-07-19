from collections.abc import Callable, Coroutine
from typing import Any

import shortuuid
from slugify import slugify


async def make_slug(
    text: str,
    duplicate_verifier: Callable[[str], Coroutine[Any, Any, bool]],
    max_length: int = 32,
    suffix_length: int = 5,
    separator: str = "-",
) -> str:
    slug = slugify(text=text, max_length=max_length, separator=separator, word_boundary=True, save_order=True)
    base_max_length = max_length - suffix_length - 1

    while await duplicate_verifier(slug):
        suffix = shortuuid.random(length=suffix_length)
        base_slug = slugify(
            text=text,
            max_length=base_max_length,
            separator=separator,
            word_boundary=True,
            save_order=True,
        )
        slug = f"{base_slug}{separator}{suffix}"
    return slug


async def make_username(
    text: str,
    duplicate_verifier: Callable[[str], Coroutine[Any, Any, bool]],
) -> str:
    return await make_slug(text, duplicate_verifier, max_length=30, suffix_length=5, separator="_")
