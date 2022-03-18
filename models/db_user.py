from __future__ import annotations

import json
import typing as t

import attr
import hikari

from models.db import DatabaseModel


@attr.define()
class DatabaseUser(DatabaseModel):
    """
    Represents user data stored inside the database.
    """

    id: hikari.Snowflake
    guild_id: hikari.Snowflake
    flags: t.Optional[dict]
    notes: t.Optional[t.List[str]]
    warns: int = 0

    async def update(self) -> None:
        """Update or insert this user into the database."""

        flags = json.dumps(self.flags) if self.flags else None
        await self._db.execute(
            """
            INSERT INTO users (user_id, guild_id, flags, warns, notes) 
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id, guild_id) DO
            UPDATE SET flags = $3, warns = $4, notes = $5""",
            self.id,
            self.guild_id,
            flags,
            self.warns,
            self.notes,
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
            return cls(hikari.Snowflake(user), hikari.Snowflake(guild), flags={}, notes=None, warns=0)

        return cls(
            id=hikari.Snowflake(record.get("user_id")),
            guild_id=hikari.Snowflake(record.get("guild_id")),
            flags=json.loads(record.get("flags")) if record.get("flags") else {},
            warns=record.get("warns"),
            notes=record.get("notes"),
        )

    @classmethod
    async def fetch_all(cls, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> t.Optional[t.List[DatabaseUser]]:
        """Fetch all stored user data that belongs to the specified guild.

        Parameters
        ----------
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild the users belongs to.

        Returns
        -------
        Optional[List[DatabaseUser]]
            A list of objects representing stored user data.
        """

        records = await cls._db.fetch("""SELECT * FROM users WHERE guild_id = $1""", hikari.Snowflake(guild))

        if not records:
            return

        return [
            cls(
                id=hikari.Snowflake(record.get("user_id")),
                guild_id=hikari.Snowflake(record.get("guild_id")),
                flags=json.loads(record.get("flags")) if record.get("flags") else {},
                warns=record.get("warns"),
                notes=record.get("notes"),
            )
            for record in records
        ]
