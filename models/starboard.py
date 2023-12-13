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

    channel_id: hikari.Snowflake | None = attr.field(default=None)
    """The channel where the starboard messages will be sent."""

    star_limit: int = attr.field(default=5)
    """The amount of stars needed to post a message to the starboard."""

    is_enabled: bool = attr.field(default=False)
    """Whether the starboard is enabled or not."""

    excluded_channels: t.Sequence[hikari.Snowflake] | None = attr.field(default=None)
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

        records = await cls._app.db_cache.get(table="starboard", guild_id=hikari.Snowflake(guild), limit=1)
        if not records:
            return cls(guild_id=hikari.Snowflake(guild))
        return cls.from_record(records[0])  # type: ignore

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


@attr.define()
class StarboardEntry(DatabaseModel):
    """Represents a starboard entry in the database."""

    guild_id: hikari.Snowflake = attr.field()
    """The guild this starboard entry belongs to."""

    channel_id: hikari.Snowflake = attr.field()
    """The channel the original message is in."""

    original_message_id: hikari.Snowflake = attr.field()
    """The message that was starred."""

    entry_message_id: hikari.Snowflake = attr.field()
    """The message that was posted to the starboard."""

    force_starred: bool = attr.field(default=False)
    """Whether the message was force starred or not."""

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> StarboardEntry:
        """Create an instance of StarboardEntry from an asyncpg.Record."""

        return cls(
            guild_id=record["guild_id"],
            channel_id=record["channel_id"],
            original_message_id=record["orig_msg_id"],
            entry_message_id=record["entry_msg_id"],
            force_starred=record["force_starred"],
        )

    @classmethod
    async def fetch(cls, original_message: hikari.SnowflakeishOr[hikari.PartialMessage]) -> StarboardEntry | None:
        """Fetch the starboard entry for a message from the database, if one exists."""

        records = await cls._app.db_cache.get(
            table="starboard_entries", orig_msg_id=hikari.Snowflake(original_message), limit=1
        )
        if not records:
            return None
        return cls.from_record(records[0])  # type: ignore

    async def update(self) -> None:
        """Update the starboard entry in the database, or insert it if it does not yet exist."""

        await self._db.execute(
            """INSERT INTO starboard_entries 
            (guild_id, channel_id, orig_msg_id, entry_msg_id, force_starred) 
            VALUES ($1, $2, $3, $4, $5) 
            ON CONFLICT (guild_id, channel_id, orig_msg_id) DO 
            UPDATE SET guild_id = $1, channel_id = $2, orig_msg_id = $3, entry_msg_id = $4, force_starred = $5""",
            self.guild_id,
            self.channel_id,
            self.original_message_id,
            self.entry_message_id,
            self.force_starred,
        )
        await self._app.db_cache.refresh(table="starboard_entries", orig_msg_id=self.original_message_id)

    async def delete(self) -> None:
        """Delete the starboard entry from the database."""

        await self._db.execute(
            "DELETE FROM starboard_entries WHERE guild_id = $1 AND orig_msg_id = $2",
            self.guild_id,
            self.original_message_id,
        )
        await self._app.db_cache.refresh(table="starboard_entries", orig_msg_id=self.original_message_id)
