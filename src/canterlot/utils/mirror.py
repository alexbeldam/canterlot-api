from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, Concatenate, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


class MirrorPool:
    def __init__(self, mirrors: list[str]):
        if not mirrors:
            raise ValueError("MirrorPool requires at least one mirror.")

        self._mirrors = mirrors
        self._preferred_index = 0
        self._lock = asyncio.Lock()

    @property
    def preferred(self) -> str:
        return self._mirrors[self._preferred_index]

    async def execute(
        self,
        operation: Callable[Concatenate[str, P], Coroutine[Any, Any, T]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        preferred = self.preferred

        try:
            return await operation(preferred, *args, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        return await self.__race_mirrors(operation, *args, **kwargs)

    async def __race_mirrors(
        self,
        operation: Callable[Concatenate[str, P], Coroutine[Any, Any, T]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        tasks: dict[asyncio.Task[T], int] = {}

        for index, mirror in enumerate(self._mirrors):
            task = asyncio.create_task(operation(mirror, *args, **kwargs))
            tasks[task] = index

        errors: list[Exception] = []

        try:
            while tasks:
                done, _ = await asyncio.wait(
                    tasks.keys(),
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    index = tasks.pop(task)

                    try:
                        result = task.result()
                    except asyncio.CancelledError:
                        continue
                    except Exception as exc:
                        errors.append(exc)
                        continue

                    async with self._lock:
                        self._preferred_index = index

                    for pending in tasks:
                        pending.cancel()

                    await asyncio.gather(
                        *tasks,
                        return_exceptions=True,
                    )

                    return result
        finally:
            for task in tasks:
                task.cancel()

            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )
        raise ExceptionGroup(
            "All mirrors failed.",
            errors,
        )
