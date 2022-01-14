import asyncio
import inspect
import logging
import signal


class Loop:
    def __init__(self, coro, seconds: float = None, minutes: float = None, hours: float = None, days: float = None):
        if not seconds and not minutes and not hours and not days:
            raise ValueError("Expected a loop time.")
        else:
            seconds = seconds or 0
            minutes = minutes or 0
            hours = hours or 0
            days = hours or 0

        self.coro = coro
        self._task = None
        self._failed = 0
        self._sleep = seconds + minutes * 60 + hours * 3600 + days * 24 * 3600
        self._stop_next = False
        self.loop = asyncio.get_event_loop()
        self.loop.add_signal_handler(signal.SIGINT, self.cancel)

        if not inspect.iscoroutinefunction(self.coro):
            raise TypeError(f"Expected a coroutine function.")

    async def _loopy_loop(self, *args, **kwargs):
        if not self._stop_next:
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
            finally:
                self._task = self.loop.create_task(self._loopy_loop())
        else:
            self.cancel()

    def start(self):
        """
        Start looping the task at the specified interval.
        """
        if self._task and not self._task.done():
            raise RuntimeError("Task is already running!")

        self._task = self.loop.create_task(self._loopy_loop())
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


def loop(*, seconds: float = None, minutes: float = None, hours: float = None, days: float = None) -> None:
    """My shoddy attempt at copying discord.py's ext.tasks functionality in it's simplest form."""

    def decorator(func):
        return Loop(func, seconds=seconds, minutes=minutes, hours=hours, days=days)

    return decorator
