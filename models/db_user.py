from __future__ import annotations

import enum
import json
import typing as t

import attr
import hikari

from models.db import DatabaseModel


class DatabaseUserFlag(enum.Flag):
    """Flags stored for a user in the database."""

    NONE = 0
    """An empty set of database user flags."""
    TIMEOUT_ON_JOIN = 1 << 0
    """The user should be timed out when next spotted joining the guild."""


@attr.define()
class DatabaseUser(DatabaseModel):
    """
    Represents user data stored inside the database.
    """

    id: hikari.Snowflake
    """The ID of this user."""

    guild_id: hikari.Snowflake
    """The guild this user is bound to."""

    flags: DatabaseUserFlag
    """A set of flags stored for this user."""

    notes: t.Optional[t.List[str]]
    """A list of journal entries stored for this user."""

    warns: int = 0
    """The count of warnings stored for this user."""

    data: t.Dict[str, t.Any] = {}
    """Miscellaneous data stored for this user. Must be JSON serializable."""

    async def update(self) -> None:
        """Update or insert this user into the database."""

        await self._db.execute(
            """
            INSERT INTO users (user_id, guild_id, flags, warns, notes, data) 
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (user_id, guild_id) DO
            UPDATE SET flags = $3, warns = $4, notes = $5, data = $6""",
            self.id,
            self.guild_id,
            self.flags.value,
            self.warns,
            self.notes,
            json.dumps(self.data),
        )

    @classmethod
    async def fetch(
        cls, user: hikari.SnowflakeishOr[hikari.PartialUser], guild: hikari.SnowflakeishOr[hikari.PartialGuild]
    ) -> DatabaseUser:
        """Fetch a user from the database. If not present, returns a default DatabaseUser object.

        Parameters
        ----------
        user : hikari.SnowflakeishOr[hikari.PartialUser]
            The user to retrieve database information for.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild the user belongs to.

        Returns
        -------
        DatabaseUser
            An object representing stored user data.
        """

        record = await cls._db.fetchrow(
            """SELECT * FROM users WHERE user_id = $1 AND guild_id = $2""",
            hikari.Snowflake(user),
            hikari.Snowflake(guild),
        )

        if not record:
            return cls(
                hikari.Snowflake(user), hikari.Snowflake(guild), flags=DatabaseUserFlag.NONE, notes=None, warns=0
            )

        return cls(
            id=hikari.Snowflake(record.get("user_id")),
            guild_id=hikari.Snowflake(record.get("guild_id")),
            flags=DatabaseUserFlag(record.get("flags")),
            warns=record.get("warns"),
            notes=record.get("notes"),
            data=json.loads(record.get("data")) if record.get("data") else {},
        )

    @classmethod
    async def fetch_all(cls, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> t.List[DatabaseUser]:
        """Fetch all stored user data that belongs to the specified guild.

        Parameters
        ----------
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild the users belongs to.

        Returns
        -------
        List[DatabaseUser]
            A list of objects representing stored user data.
        """

        records = await cls._db.fetch("""SELECT * FROM users WHERE guild_id = $1""", hikari.Snowflake(guild))

        if not records:
            return []

        return [
            cls(
                id=hikari.Snowflake(record.get("user_id")),
                guild_id=hikari.Snowflake(record.get("guild_id")),
                flags=DatabaseUserFlag(record.get("flags")),
                warns=record.get("warns"),
                notes=record.get("notes"),
                data=json.loads(record.get("data")) if record.get("data") else {},
            )
            for record in records
        ]


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
