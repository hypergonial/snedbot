from __future__ import annotations

import logging
import re
import typing as t

import hikari

from models.db import DatabaseModel

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    from models import SnedBot


class DatabaseCache:
    """
    A class aimed squarely at making caching of values easier to handle, and
    centralize it. It tries lazy-loading a dict whenever requesting data,
    or setting it.
    """

    def __init__(self, bot: SnedBot) -> None:
        self.bot: SnedBot = bot
        self._cache: t.Dict[str, t.List[t.Dict[str, t.Any]]] = {}
        self.is_ready: bool = False

    def _clean_kwarg(self, kwarg: str) -> str:
        return re.sub(r"\W|^(?=\d)", "_", kwarg)

    async def start(self) -> None:
        """
        Initialize the database cache. This should be called after the database is set up.
        """
        self.is_ready = False
        self._cache = {}
        DatabaseModel._db_cache = self

        records = await self.bot.db.fetch(
            """
        SELECT tablename FROM pg_catalog.pg_tables 
        WHERE schemaname='public'
        """
        )
        for record in records:
            self._cache[record.get("tablename")] = []
        logger.info("Cache initialized!")
        self.is_ready = True

    # Leaving this as async for potential future functionality
    async def stop(self) -> None:
        """
        Disable the cache and wipe all of it's contents.
        """
        self.is_ready = False
        self._cache = {}

    async def get(
        self, table: str, *, cache_only: bool = False, limit: t.Optional[int] = None, **kwargs: t.Any
    ) -> t.Optional[t.List[t.Dict[str, t.Any]]]:
        """Get a value from the database cache, lazily fetches from the database if the value is not cached.

        Parameters
        ----------
        table : str
            The table to get values from
        cache_only : bool, optional
            Set to True if fetching from the database is undesirable, by default False
        limit : Optional[int], optional
            The maximum amount of rows to return, by default None
        **kwargs: t.Any, optional
            Keyword-only arguments that denote columns to filter values.

        Returns
        -------
        Optional[List[Dict[str, Any]]]
            A list of dicts representing the rows in the specified table.
        """
        if not self.is_ready:
            return

        rows: t.List[t.Dict[str, t.Any]] = []

        for row in self._cache[table]:
            if limit and len(rows) >= limit:
                break

            # Check if all kwargs match what is in the row
            if all([row[kwarg] == value for kwarg, value in kwargs.items()]):
                rows.append(row)

        if not rows and not cache_only:
            await self.refresh(table, **kwargs)

            for row in self._cache[table]:
                if limit and len(rows) >= limit:
                    break

                if all([row[kwarg] == value for kwarg, value in kwargs.items()]):
                    rows.append(row)
        if rows:
            return rows

    async def refresh(self, table: str, **kwargs) -> None:
        """
        Discards and reloads a specific part of the cache, should be called after modifying database values.
        """
        if not self.is_ready:
            return

        if self._cache.get(table) is None:
            raise ValueError("Invalid table specified.")

        # Construct sql args, remove invalid python chars
        sql_args = [f"{self._clean_kwarg(kwarg)} = ${i+1}" for i, kwarg in enumerate(kwargs)]
        records = await self.bot.db.fetch(f"""SELECT * FROM {table} WHERE {' AND '.join(sql_args)}""", *kwargs.values())

        for i, row in enumerate(self._cache[table]):
            # Pop old values that match the kwargs
            if all([row[kwarg] == value for kwarg, value in kwargs.items()]):
                self._cache[table].pop(i)

        for record in records:
            self._cache[table].append(dict(record))

    async def wipe(self, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> None:
        """
        Discards the entire cache for a guild.
        """
        if not self.is_ready:
            return

        guild_id = hikari.Snowflake(guild)

        for table in self._cache.keys():
            for i, row in enumerate(self._cache[table]):
                if row.get("guild_id") == guild_id:
                    self._cache[table].pop(i)


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
