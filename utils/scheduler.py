import asyncio
import datetime
import logging
import re

from dateutil import parser as dateparser
import hikari
import Levenshtein as lev
from models.events import TimerCompleteEvent
from models.timer import Timer
from utils.tasks import IntervalLoop

logger = logging.getLogger(__name__)


class Scheduler:
    """
    All timer-related functionality, including time conversion from strings,
    creation, scheduling & dispatching of timers.
    Essentially the internal scheduler of the bot.
    """

    def __init__(self, bot):

        self.bot = bot
        self.current_timer = None
        self.currenttask = None
        self.timer_loop = IntervalLoop(self.wait_for_active_timers, hours=1.0)
        self.timer_loop.start()

    async def convert_time(self, timestr: str, force_mode: str = None) -> datetime.datetime:
        """
        Tries converting a string to datetime.datetime via regex, returns datetime.datetime if successful.
        Raises ValueError if time is invalid or not in the future.
        """

        logger.debug(f"String passed for time conversion: {timestr}")

        if not force_mode or force_mode == "absolute":

            try:
                time = dateparser.parse(timestr)
            except Exception:
                if force_mode == "absolute":  # Only raise exception if this is the only conversion attempted
                    raise
            else:
                if not time.tzinfo:
                    time = datetime.datetime.fromtimestamp(time.timestamp(), tz=datetime.timezone.utc)
                if time > datetime.datetime.now(datetime.timezone.utc):
                    return time

        if not force_mode or force_mode == "relative":
            # Relative time conversion
            # Get any pair of <number><word> with a single optional space in between, and return them as a dict (sort of)
            time_regex = re.compile(r"(\d+(?:[.,]\d+)?)\s{0,1}([a-zA-Z]+)")
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

            for val, category in matches:
                val = val.replace(",", ".")  # Replace commas with periods to correctly register decimal places
                # If this is a single letter

                if len(category) == 1:
                    if category in time_letter_dict.keys():
                        time += time_letter_dict[category] * float(val)

                else:
                    # If a partial match is found with any of the keys
                    # Reason for making the same code here is because words are case-insensitive, as opposed to single letters

                    for string in time_word_dict.keys():
                        if (
                            lev.distance(category.lower(), string.lower()) <= 1
                        ):  # If str has 1 or less different letters (For plural)
                            time += time_word_dict[string] * float(val)
                            break

            if time > 0:

                time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=time)
            else:  # If time is 0, then we failed to parse or the user indeed provided 0, which makes no sense, so we raise an error.
                raise ValueError("Failed converting time from string. (Relative conversion)")

            return time

    async def get_latest_timer(self, days=7):
        """
        Gets the first timer that is about to expire in the specified days and returns it
        Returns None if not found in that scope.
        """
        await self.bot.wait_until_started()
        logger.debug("Getting latest timer...")
        result = await self.bot.pool.fetch(
            """SELECT * FROM timers WHERE expires < $1 ORDER BY expires LIMIT 1""",
            round((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).timestamp()),
        )
        logger.debug(f"Latest timer from db: {result}")

        if len(result) != 0 and result[0]:
            timer = Timer(
                id=result[0].get("id"),
                guild_id=result[0].get("guild_id"),
                user_id=result[0].get("user_id"),
                channel_id=result[0].get("channel_id"),
                event=result[0].get("event"),
                expires=result[0].get("expires"),
                notes=result[0].get("notes"),
            )

            logger.debug(f"Timer class created for latest: {timer}")
            return timer

    async def call_timer(self, timer: Timer):
        """
        Calls and dispatches a timer object. Updates the database.
        """

        logger.debug("Deleting timer entry {timerid}".format(timerid=timer.id))
        await self.bot.pool.execute("""DELETE FROM timers WHERE id = $1""", timer.id)

        self.current_timer = None
        logger.debug("Deleted")

        """
        Dispatch an event named eventname_timer_complete, which will cause all listeners 
        for this event to fire. This function is not documented, so if anything breaks, it
        is probably in here. It passes on the Timer
        """
        event = TimerCompleteEvent(app=self.bot, timer=timer)

        self.bot.dispatch(event)
        logger.info(f"Dispatched: TimerCompleteEvent for {timer.event}")

    async def dispatch_timers(self):
        """
        A coroutine to dispatch timers.
        """
        logger.debug("Dispatching timers.")
        try:
            while self.bot.is_ready:
                logger.debug("Getting timer")

                timer = await self.get_latest_timer(days=40)
                self.current_timer = timer

                now = round(datetime.datetime.now(datetime.timezone.utc).timestamp())
                logger.debug(f"Now: {now}")
                logger.debug(f"Timer: {timer}")

                if timer:

                    if timer.expires >= now:
                        sleep_time = timer.expires - now
                        logger.info(f"Awaiting next timer: '{timer.event}', which is in {sleep_time}s")
                        await asyncio.sleep(sleep_time)

                    logger.info(f"Dispatching timer: {timer.event}")
                    await self.call_timer(timer)

                else:
                    break  # Avoid infinite loop

        except asyncio.CancelledError:
            raise
        except (OSError, hikari.GatewayServerClosedConnectionError):
            self.currenttask.cancel()
            self.currenttask = asyncio.create_task(self.dispatch_timers())

    async def update_timer(
        self,
        expires: datetime.datetime,
        entry_id: int,
        guild_id: int,
        new_notes: str = None,
    ):
        """Update a timer's expiry and/or notes field."""

        expires = round(expires.timestamp())
        if new_notes:
            await self.bot.pool.execute(
                """UPDATE timers SET expires = $1, notes = $2 WHERE id = $3 AND guild_id = $4""",
                expires,
                new_notes,
                entry_id,
                guild_id,
            )
        else:
            await self.bot.pool.execute(
                """UPDATE timers SET expires = $1 WHERE id = $2 AND guild_id = $3""",
                expires,
                entry_id,
                guild_id,
            )
        if self.current_timer and self.current_timer.id == entry_id:
            logger.debug("Updating timers resulted in reshuffling.")
            self.currenttask.cancel()
            self.currenttask = asyncio.create_task(self.dispatch_timers())

    async def get_timer(self, entry_id: int, guild_id: int) -> Timer:
        """Retrieve a pending timer"""

        records = await self.bot.pool.fetch(
            """SELECT * FROM timers WHERE id = $1 AND guild_id = $2""",
            entry_id,
            guild_id,
        )

        if records and len(records) > 0:
            record = records[0]
            timer = Timer(
                record.get("id"),
                record.get("guild_id"),
                record.get("user_id"),
                record.get("event"),
                record.get("channel_id"),
                record.get("expires"),
                record.get("notes"),
            )
            return timer

        else:
            raise ValueError("Invalid entry_id or guild_id: Timer not found.")

    async def create_timer(
        self,
        expires: datetime.datetime,
        event: str,
        guild_id: int,
        user_id: int,
        channel_id: int = None,
        *,
        notes: str = None,
    ) -> Timer:
        """Create a new timer, will dispatch on_<event>_timer_complete when finished."""

        expires = round(expires.timestamp())  # Converting it to time since epoch
        records = await self.bot.pool.fetch(
            """INSERT INTO timers (guild_id, channel_id, user_id, event, expires, notes) VALUES ($1, $2, $3, $4, $5, $6) RETURNING *""",
            guild_id,
            channel_id,
            user_id,
            event,
            expires,
            notes,
        )
        record = records[0]
        timer = Timer(
            record.get("id"),
            record.get("guild_id"),
            record.get("user_id"),
            record.get("event"),
            record.get("channel_id"),
            record.get("expires"),
            record.get("notes"),
        )

        # If there is already a timer in queue, and it has an expiry that is further than the timer we just created
        # Then we reboot the dispatch_timers() function to re-check for the latest timer.
        if self.current_timer and expires < self.current_timer.expires:
            logger.debug("Reshuffled timers, this is now the latest timer.")
            self.currenttask.cancel()
            self.currenttask = asyncio.create_task(self.dispatch_timers())
        elif self.current_timer is None:
            self.currenttask = asyncio.create_task(self.dispatch_timers())
        return timer

    async def cancel_timer(self, entry_id: int, guild_id: int) -> Timer:
        """Prematurely cancel a timer before expiry. Returns the cancelled timer."""
        try:
            timer = await self.get_timer(entry_id, guild_id)
        except ValueError:
            raise
        else:
            await self.bot.pool.execute(
                """DELETE FROM timers WHERE id = $1 AND guild_id = $2""", timer.id, timer.guild_id
            )
            if self.current_timer and self.current_timer.id == int(timer.id):
                self.currenttask.cancel()
                self.currenttask = asyncio.create_task(self.dispatch_timers())
            return timer

    async def wait_for_active_timers(self):
        """
        Check every hour to see if new timers meet criteria in the database.
        """
        if self.currenttask is None:
            self.currenttask = asyncio.create_task(self.dispatch_timers())
