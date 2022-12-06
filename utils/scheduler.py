from __future__ import annotations

import asyncio
import datetime
import enum
import logging
import re
import typing
import typing as t

import dateparser
import hikari
import Levenshtein as lev

from models.events import TimerCompleteEvent
from models.timer import Timer, TimerEvent
from utils.tasks import IntervalLoop

logger = logging.getLogger(__name__)


if typing.TYPE_CHECKING:
    from models.bot import SnedBot


class ConversionMode(enum.IntEnum):
    """All possible time conversion modes."""

    RELATIVE = 0
    ABSOLUTE = 1


class Scheduler:
    """
    All timer-related functionality, including time conversion from strings,
    creation, scheduling & dispatching of timers.
    Essentially the internal scheduler of the bot.
    """

    def __init__(self, bot: SnedBot) -> None:
        self.bot: SnedBot = bot
        self._current_timer: t.Optional[Timer] = None  # Currently active timer that is being awaited
        self._current_task: t.Optional[asyncio.Task] = None  # Current task that is handling current_timer
        self._timer_loop: IntervalLoop = IntervalLoop(self._wait_for_active_timers, hours=1.0)
        self._is_started: bool = False

    def start(self) -> None:
        """
        Start the scheduler.
        """
        self._timer_loop.start()
        self._is_started = True
        logger.info("Scheduler startup complete.")

    def restart(self) -> None:
        """
        Restart the scheduler.
        """
        self._is_started = False
        if self._current_task is not None:
            self._current_task.cancel()
        self._current_task = None
        self._current_timer = None
        self._timer_loop.cancel()
        self._timer_loop.start()
        self._is_started = True
        logger.info("Scheduler restart complete.")

    def stop(self) -> None:
        """
        Stop the scheduler.
        """
        self._is_started = False
        self._timer_loop.cancel()
        if self._current_task is not None:
            self._current_task.cancel()
        self._current_timer = None
        logger.info("Scheduler shutdown complete.")

    async def convert_time(
        self,
        timestr: str,
        *,
        user: t.Optional[hikari.SnowflakeishOr[hikari.PartialUser]] = None,
        conversion_mode: t.Optional[ConversionMode] = None,
        future_time: bool = False,
    ) -> datetime.datetime:
        """Try converting a string of human-readable time to a datetime object.

        Parameters
        ----------
        timestr : str
            The string containing the time.
        user : t.Optional[hikari.SnowflakeishOr[hikari.PartialUser]], optional
            The user whose preferences will be used in the case of timezones, by default None
        force_mode : t.Optional[str], optional
            If specified, forces either 'relative' or 'absolute' conversion, by default None
        future_time : bool, optional
            If True and the time specified is in the past, raise an error, by default False

        Returns
        -------
        datetime.datetime
            The converted datetime.datetime object.

        Raises
        ------
        ValueError
            Time could not be parsed using relative conversion.
        ValueError
            Time could not be parsed using absolute conversion.
        ValueError
            Time is not in the future.
        """
        user_id = hikari.Snowflake(user) if user else None
        logger.debug(f"String passed for time conversion: {timestr}")

        if not conversion_mode or conversion_mode == ConversionMode.RELATIVE:
            # Relative time conversion
            # Get any pair of <number><word> with a single optional space in between, and return them as a dict (sort of)
            time_regex = re.compile(r"(\d+(?:[.,]\d+)?)\s?(\w+)")
            time_letter_dict = {
                "h": 3600,
                "s": 1,
                "m": 60,
                "d": 86400,
                "w": 86400 * 7,
                "M": 86400 * 30,
                "Y": 86400 * 365,
                "y": 86400 * 365,
            }
            time_word_dict = {
                "hour": 3600,
                "second": 1,
                "minute": 60,
                "day": 86400,
                "week": 86400 * 7,
                "month": 86400 * 30,
                "year": 86400 * 365,
                "sec": 1,
                "min": 60,
            }
            matches = time_regex.findall(timestr)
            time = 0

            for input, category in matches:
                input = input.replace(",", ".")  # Replace commas with periods to correctly register decimal places
                # If this is a single letter

                if len(category) == 1:
                    if value := time_letter_dict.get(category):
                        time += value * float(input)

                else:
                    for string, value in time_word_dict.items():
                        if (
                            category.lower() == string or category.lower()[:-1] == string
                        ):  # Account for plural forms of the word
                            time += value * float(input)
                            break

            if time > 0:  # If we found time
                return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=time)

            if conversion_mode == ConversionMode.RELATIVE:
                raise ValueError("Failed time conversion. (relative)")

        if not conversion_mode or conversion_mode == ConversionMode.ABSOLUTE:

            timezone = "UTC"
            if user_id:
                records = await self.bot.db_cache.get(table="preferences", user_id=user_id, limit=1)
                timezone = records[0].get("timezone") if records else "UTC"
                assert timezone is not None  # Fucking pointless, I hate you pyright

            time = dateparser.parse(
                timestr, settings={"RETURN_AS_TIMEZONE_AWARE": True, "TIMEZONE": timezone, "NORMALIZE": True}
            )

            if not time:
                raise ValueError("Time could not be parsed. (absolute)")

            if future_time and time < datetime.datetime.now(datetime.timezone.utc):
                raise ValueError("Time is not in the future!")

            return time

        raise ValueError("Time conversion failed.")

    async def get_latest_timer(self, days: int = 5) -> t.Optional[Timer]:
        """Gets the latest timer in the specified range of days.

        Parameters
        ----------
        days : int, optional
            The maximum expiry of the timer, by default 5

        Returns
        -------
        Optional[Timer]
            The timer object that was found, if any.
        """
        await self.bot.wait_until_started()
        record = await self.bot.db.fetchrow(
            """SELECT * FROM timers WHERE expires < $1 ORDER BY expires LIMIT 1""",
            round((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).timestamp()),
        )

        if record:
            timer = Timer(
                id=record.get("id"),
                guild_id=hikari.Snowflake(record.get("guild_id")),
                user_id=hikari.Snowflake(record.get("user_id")),
                channel_id=hikari.Snowflake(record.get("channel_id")) if record.get("channel_id") else None,
                event=TimerEvent(record.get("event")),
                expires=record.get("expires"),
                notes=record.get("notes"),
            )
            return timer

    async def _call_timer(self, timer: Timer) -> None:
        """Calls the provided timer, dispatches TimerCompleteEvent, and removes the timer object from
        the database.

        Parameters
        ----------
        timer : Timer
            The timer to be called.
        """

        await self.bot.db.execute("""DELETE FROM timers WHERE id = $1""", timer.id)

        self._current_timer = None
        event = TimerCompleteEvent(self.bot, timer, timer.guild_id)

        self.bot.dispatch(event)
        logger.info(f"Dispatched TimerCompleteEvent for {timer.event.value} (ID: {timer.id})")

    async def _dispatch_timers(self):
        """
        A task that loops, waits for, and calls pending timers.
        """
        try:
            while self.bot.is_ready and self._is_started:

                timer = await self.get_latest_timer(days=30)
                self._current_timer = timer

                now = round(datetime.datetime.now(datetime.timezone.utc).timestamp())

                if not timer:
                    break

                if timer.expires >= now:
                    sleep_time = timer.expires - now
                    logger.info(
                        f"Awaiting next timer: '{timer.event.value}' (ID: {timer.id}), which is in {sleep_time}s"
                    )
                    await asyncio.sleep(sleep_time)

                # TODO: Maybe some sort of queue system so we do not spam out timers like crazy after restart?
                logger.info(f"Dispatching timer: {timer.event.value} (ID: {timer.id})")
                await self._call_timer(timer)

        except asyncio.CancelledError:
            raise
        except (OSError, hikari.GatewayServerClosedConnectionError):
            if self._current_task:
                self._current_task.cancel()
            self._current_task = asyncio.create_task(self._dispatch_timers())

    async def update_timer(self, timer: Timer) -> None:
        """Update a currently running timer, replacing it with the specified timer object.
        If needed, reshuffles timers.

        Parameters
        ----------
        timer : Timer
            The timer object to update.
        """
        if not self._is_started:
            raise hikari.ComponentStateConflictError("The scheduler is not running.")

        await self.bot.db.execute(
            """UPDATE timers SET user_id = $1, channel_id = $2, event = $3, expires = $4, notes = $5 WHERE id = $6 AND guild_id = $7""",
            timer.user_id,
            timer.channel_id,
            timer.event.value,
            timer.expires,
            timer.notes,
            timer.id,
            timer.guild_id,
        )
        if self._current_timer and timer.expires <= self._current_timer.expires:
            if self._current_task:
                self._current_task.cancel()
            self._current_task = asyncio.create_task(self._dispatch_timers())

    async def get_timer(self, entry_id: int, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> Timer:
        """Retrieve a currently pending timer.

        Parameters
        ----------
        entry_id : int
            The ID of the timer object.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild this timer belongs to.

        Returns
        -------
        Timer
            The located timer object.

        Raises
        ------
        ValueError
            The timer was not found.
        """

        guild_id = hikari.Snowflake(guild)
        record = await self.bot.db.fetchrow(
            """SELECT * FROM timers WHERE id = $1 AND guild_id = $2 LIMIT 1""",
            entry_id,
            guild_id,
        )

        if record:
            timer = Timer(
                record.get("id"),
                hikari.Snowflake(record.get("guild_id")),
                hikari.Snowflake(record.get("user_id")),
                hikari.Snowflake(record.get("channel_id")) if record.get("channel_id") else None,
                TimerEvent(record.get("event")),
                record.get("expires"),
                record.get("notes"),
            )
            return timer

        else:
            raise ValueError("Invalid entry_id or guild: Timer not found.")

    async def create_timer(
        self,
        expires: datetime.datetime,
        event: TimerEvent,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        user: hikari.SnowflakeishOr[hikari.PartialUser],
        channel: t.Optional[hikari.SnowflakeishOr[hikari.TextableChannel]] = None,
        *,
        notes: t.Optional[str] = None,
    ) -> Timer:
        """Create a new timer and schedule it.

        Parameters
        ----------
        expires : datetime.datetime
            The expiry date of the timer. Must be in the future.
        event : TimerEvent
            The event string to identify this timer by.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild this timer belongs to.
        user : hikari.SnowflakeishOr[hikari.PartialUser]
            The user this timer belongs to.
        channel : t.Optional[hikari.SnowflakeishOr[hikari.TextableChannel]], optional
            The channel to bind this timer to, by default None
        notes : t.Optional[str], optional
            Optional parameters or data to include, by default None

        Returns
        -------
        Timer
            The timer object that got created.
        """
        if not self._is_started:
            raise hikari.ComponentStateConflictError("The scheduler is not running.")

        guild_id = hikari.Snowflake(guild)
        user_id = hikari.Snowflake(user)
        channel_id = hikari.Snowflake(channel) if channel else None
        timestamp = round(expires.timestamp())

        records = await self.bot.db.fetch(
            """INSERT INTO timers (guild_id, channel_id, user_id, event, expires, notes) VALUES ($1, $2, $3, $4, $5, $6) RETURNING *""",
            guild_id,
            channel_id,
            user_id,
            event.value,
            timestamp,
            notes,
        )
        record = records[0]
        timer = Timer(
            record.get("id"),
            hikari.Snowflake(record.get("guild_id")),
            hikari.Snowflake(record.get("user_id")),
            hikari.Snowflake(record.get("channel_id")) if record.get("channel_id") else None,
            TimerEvent(record.get("event")),
            record.get("expires"),
            record.get("notes"),
        )

        # If there is already a timer in queue, and it has an expiry that is further than the timer we just created
        # then we restart the dispatch_timers() to re-check for the latest timer.
        if self._current_timer and timestamp < self._current_timer.expires:
            logger.debug("Reshuffled timers, created timer is now the latest timer.")
            if self._current_task:
                self._current_task.cancel()
            self._current_task = asyncio.create_task(self._dispatch_timers())

        elif self._current_timer is None:
            self._current_task = asyncio.create_task(self._dispatch_timers())

        return timer

    async def cancel_timer(self, entry_id: int, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> Timer:
        """Prematurely cancel a timer before expiry. Returns the cancelled timer.

        Parameters
        ----------
        entry_id : int
            The ID of the timer to be cancelled.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild the timer belongs to.

        Returns
        -------
        Timer
            The cancelled timer object.
        """
        if not self._is_started:
            raise hikari.ComponentStateConflictError("The scheduler is not running.")

        guild_id = hikari.Snowflake(guild)
        try:
            timer = await self.get_timer(entry_id, guild_id)
        except ValueError:
            raise
        else:
            await self.bot.db.execute(
                """DELETE FROM timers WHERE id = $1 AND guild_id = $2""", timer.id, timer.guild_id
            )

            if self._current_timer and self._current_timer.id == timer.id:
                if self._current_task:
                    self._current_task.cancel()
                self._current_task = asyncio.create_task(self._dispatch_timers())

            return timer

    async def _wait_for_active_timers(self) -> None:
        """
        Check every hour to see if new timers meet criteria in the database.
        """
        await self.bot.wait_until_started()

        if self._current_task is None:
            self._current_task = asyncio.create_task(self._dispatch_timers())


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
