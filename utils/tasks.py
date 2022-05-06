import asyncio
import inspect
import logging
import traceback
import typing as t


class IntervalLoop:
    def __init__(
        self,
        callback,
        seconds: t.Optional[float] = None,
        minutes: t.Optional[float] = None,
        hours: t.Optional[float] = None,
        days: t.Optional[float] = None,
    ) -> None:
        if not seconds and not minutes and not hours and not days:
            raise ValueError("Expected a loop time.")
        else:
            seconds = seconds or 0
            minutes = minutes or 0
            hours = hours or 0
            days = hours or 0

        self._coro = callback
        self._task: t.Optional[asyncio.Task] = None
        self._failed: int = 0
        self._sleep: float = seconds + minutes * 60 + hours * 3600 + days * 24 * 3600
        self._stop_next: bool = False

        if not inspect.iscoroutinefunction(self._coro):
            raise TypeError(f"Expected a coroutine function.")

    async def _loopy_loop(self, *args, **kwargs) -> None:
        while not self._stop_next:
            try:
                await self._coro(*args, **kwargs)
            except Exception as e:
                logging.error(f"Task encountered exception: {e}")
                traceback_msg = "\n".join(traceback.format_exception(type(e), e, e.__traceback__))
                logging.error(traceback_msg)

                if self._failed < 3:
                    self._failed += 1
                    await asyncio.sleep(self._sleep)
                else:
                    raise RuntimeError(f"Task failed repeatedly, stopping it. Exception: {e}")
            else:
                await asyncio.sleep(self._sleep)
        self.cancel()

    def start(self, *args, **kwargs) -> None:
        """
        Start looping the task at the specified interval.
        """
        if self._task and not self._task.done():
            raise RuntimeError("Task is already running!")

        self._task = asyncio.create_task(self._loopy_loop(*args, **kwargs))

    def cancel(self) -> None:
        """
        Cancel the looping of the task.
        """
        if not self._task:
            return

        self._task.cancel()
        self._task = None

    def stop(self) -> None:
        """
        Gracefully stop the looping of the task.
        """
        if self._task and not self._task.done():
            self._stop_next = True


# Copyright (C) 2022-present HyperGH

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see: https://www.gnu.org/licenses
