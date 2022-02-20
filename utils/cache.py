from __future__ import annotations

import logging
import re
import typing as t

import hikari

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    from models import SnedBot


class Caching:
    """
    A class aimed squarely at making caching of values easier to handle, and
    centralize it. It tries lazy-loading a dict whenever requesting data,
    or setting it.
    """

    def __init__(self, bot: SnedBot) -> None:
        self.bot: SnedBot = bot
        self.cache: t.Dict[str, t.Any] = {}
        self.is_ready: bool = False
        self.bot.loop.create_task(self.startup())

    async def startup(self) -> None:
        """
        Creates an empty dict for every table in the database
        """

        await self.bot.wait_until_started()
        records = await self.bot.pool.fetch(
            """
        SELECT * FROM pg_catalog.pg_tables 
        WHERE schemaname='public'
        """
        )
        for record in records:
            self.cache[record.get("tablename")] = {}
        logger.info("Cache initialized!")
        self.is_ready = True

    async def format_records(self, records: dict) -> t.List[t.Dict[str, t.Any]]:
        """
        Helper function that transforms a record into an easier to use format.
        Returns a list of dicts, each representing a row in the database.
        """
        first_key = list(records.keys())[0]
        records_fmt = []

        for i, value in enumerate(records[first_key]):
            record = {}
            for key in records.keys():

                record[key] = records[key][i]

            records_fmt.append(record)

        return records_fmt

    async def get(
        self, table: str, guild_id: t.Union[int, hikari.Snowflake], **kwargs
    ) -> t.Optional[t.List[t.Dict[str, t.Any]]]:
        """
        Finds a value based on criteria provided as keyword arguments.
        If no keyword arguments are present, returns all values for that guild_id.
        Tries getting the value from cache, if it is not present,
        goes to the database & retrieves it. Lazy-loads the cache.

        Returns a list of dicts with each dict being a row, and the dict-keys being the columns.

        Example:
        await Caching.get(table="mytable", guild_id=1234, my_column=my_value)

        This is practically equivalent to an SQL 'SELECT * FROM table WHERE' statement.
        """
        if guild_id in self.cache[table].keys():

            if kwargs:
                logger.debug("Loading data from cache and filtering...")
                matches = {}
                records = self.cache[table][guild_id]

                if not records:
                    return

                for (key, value) in kwargs.items():
                    if key in records.keys():  # If the key is found in cache
                        matches[key] = [i for i, x in enumerate(records[key]) if x == value]
                    else:
                        raise ValueError(f"Key {key} could not be found in cache.")

                # Find common elements present in all match lists
                intersection = list(set.intersection(*map(set, matches.values())))
                if len(intersection) > 0:

                    filtered_records = {key: [] for key in records.keys()}

                    for match in intersection:  # Go through every list, and check the matched positions,
                        for (key, value) in records.items():
                            filtered_records[key].append(value[match])  # Then filter them out

                    if len(filtered_records) > 0:
                        return await self.format_records(filtered_records)

            else:
                logger.debug("Loading data from cache...")
                if len(self.cache[table][guild_id]) > 0:
                    return await self.format_records(self.cache[table][guild_id])

        else:
            logger.debug("Loading data from database and loading into cache...")
            await self.refresh(table, guild_id)
            return await self.get(table, guild_id, **kwargs)

    async def refresh(self, table: str, guild_id: t.Union[int, hikari.Snowflake]) -> None:
        """
        Discards and reloads a specific part of the cache, should be called after modifying database values.
        """
        self.cache[table][guild_id] = {}
        records = await self.bot.pool.fetch(f"""SELECT * FROM {table} WHERE guild_id = $1""", guild_id)
        for record in records:
            for (field, value) in record.items():
                if self.cache[table][guild_id].get(field):
                    self.cache[table][guild_id][field].append(value)
                else:
                    self.cache[table][guild_id][field] = [value]

        logger.debug(f"Refreshed cache for table {table}, guild {guild_id}!")

    async def wipe(self, guild_id: t.Union[int, hikari.Snowflake]) -> None:
        """
        Discards the entire cache for a guild.
        """
        for table in self.cache.keys():
            self.cache[table][guild_id] = {}
