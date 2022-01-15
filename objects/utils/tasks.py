import asyncio
import inspect
import logging


class IntervalLoop:
    def __init__(self, callback, seconds: float = None, minutes: float = None, hours: float = None, days: float = None):
        if not seconds and not minutes and not hours and not days:
            raise ValueError("Expected a loop time.")
        else:
            seconds = seconds or 0
            minutes = minutes or 0
            hours = hours or 0
            days = hours or 0

        self.coro = callback
        self._task = None
        self._failed = 0
        self._sleep = seconds + minutes * 60 + hours * 3600 + days * 24 * 3600
        self._stop_next = False

        if not inspect.iscoroutinefunction(self.coro):
            raise TypeError(f"Expected a coroutine function.")

    async def _loopy_loop(self, *args, **kwargs):
        while not self._stop_next:
            try:
                await self.coro(*args, **kwargs)
            except Exception as e:
                if self._failed < 3:
                    self._failed += 1
                    logging.error(f"Task encountered exception: {e}")
                    await asyncio.sleep(self._sleep)
                else:
                    raise RuntimeError(f"Task failed repeatedly, stopping it. Exception: {e}")
            else:
                await asyncio.sleep(self._sleep)
        self.cancel()

    def start(self, *args, **kwargs):
        """
        Start looping the task at the specified interval.
        """
        if self._task and not self._task.done():
            raise RuntimeError("Task is already running!")

        self._task = asyncio.create_task(self._loopy_loop(*args, **kwargs))
        return self._task

    def cancel(self):
        """
        Cancel the looping of the task.
        """
        if not self._task:
            raise RuntimeError("Task is not running!")

        self._task.cancel()
        self._task = None

    def stop(self):
        """
        Gracefully stop the looping of the task.
        """
        if not self._task and not self._task.done():
            self._stop_next = True
