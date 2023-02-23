from __future__ import annotations

import typing as t

import asyncpg
import attr
import hikari

from .db import DatabaseModel


@attr.define()
class StarboardSettings(DatabaseModel):
    """Represents the starboard settings for a guild."""

    guild_id: hikari.Snowflake = attr.field()
    """The guild this starboard settings belongs to."""

    channel_id: t.Optional[hikari.Snowflake] = attr.field(default=None)
    """The channel where the starboard messages will be sent."""

    star_limit: int = attr.field(default=5)
    """The amount of stars needed to post a message to the starboard."""

    is_enabled: bool = attr.field(default=False)
    """Whether the starboard is enabled or not."""

    excluded_channels: t.Optional[t.Sequence[hikari.Snowflake]] = attr.field(default=None)
    """Channels that are excluded from the starboard."""

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> StarboardSettings:
        """Create an instance of StarboardSettings from an asyncpg.Record."""

        return cls(
            guild_id=record["guild_id"],
            channel_id=record["channel_id"],
            star_limit=record["star_limit"],
            is_enabled=record["is_enabled"],
            excluded_channels=record["excluded_channels"],
        )

    @classmethod
    async def fetch(cls, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> StarboardSettings:
        """Fetch the starboard settings for a guild from the database. If they do not exist, return default values."""

        record = await cls._app.db_cache.get(table="starboard", guild_id=hikari.Snowflake(guild), limit=1)
        if not record:
            return cls(guild_id=hikari.Snowflake(guild))
        return cls.from_record(record)

    async def update(self) -> None:
        """Update the starboard settings in the database, or insert them if they do not yet exist."""

        await self._db.execute(
            """INSERT INTO starboard 
            (guild_id, channel_id, star_limit, is_enabled, excluded_channels) 
            VALUES ($1, $2, $3, $4, $5) 
            ON CONFLICT (guild_id) DO 
            UPDATE SET channel_id = $2, star_limit = $3, is_enabled = $4, excluded_channels = $5""",
            self.guild_id,
            self.channel_id,
            self.star_limit,
            self.is_enabled,
            self.excluded_channels,
        )
        await self._app.db_cache.refresh(table="starboard", guild_id=self.guild_id)
