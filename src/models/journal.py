from __future__ import annotations

import datetime
import enum
import typing as t

import attr
import hikari

from src.models.db import DatabaseModel
from src.utils import helpers

if t.TYPE_CHECKING:
    import asyncpg


class JournalEntryType(enum.IntEnum):
    BAN = 0
    UNBAN = 1
    KICK = 2
    TIMEOUT = 3
    TIMEOUT_REMOVE = 4
    NOTE = 5
    WARN = 6
    WARN_REMOVE = 7
    WARN_CLEAR = 8


ENTRY_TYPE_VERB_MAPPING = {
    JournalEntryType.BAN: "🔨 Banned",
    JournalEntryType.UNBAN: "🔨 Unbanned",
    JournalEntryType.KICK: "👢 Kicked",
    JournalEntryType.TIMEOUT: "🔇 Timed out",
    JournalEntryType.TIMEOUT_REMOVE: "🔉 Timeout removed",
    JournalEntryType.NOTE: "💬 Note",
    JournalEntryType.WARN: "⚠️ Warned",
    JournalEntryType.WARN_REMOVE: "⚠️ 1 Warning removed",
    JournalEntryType.WARN_CLEAR: "⚠️ Warnings cleared",
}


@attr.define()
class JournalEntry(DatabaseModel):
    """Represents a journal entry created through the /journal command."""

    user_id: hikari.Snowflake
    """The user this journal entry belongs to."""
    guild_id: hikari.Snowflake
    """The guild this entry belongs to."""
    content: str | None
    """The content of the entry."""
    author_id: hikari.Snowflake | None
    """The user who caused this entry to be created."""
    created_at: datetime.datetime
    """UNIX timestamp of the entry's creation."""
    entry_type: JournalEntryType
    """The type of this entry."""
    id: int | None = None
    """The ID of the journal entry."""

    @property
    def display_content(self) -> str:
        """Get the content of the entry, with a timestamp prepended."""
        author_mention = f"<@{self.author_id}>" if self.author_id else "Unknown"
        content = self.content or "Error retrieving data from audit logs! Ensure the bot has permissions to view them!"
        return f"{helpers.format_dt(self.created_at, style='d')} **{ENTRY_TYPE_VERB_MAPPING.get(self.entry_type, '')} by {author_mention}**: {content}"

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> t.Self:
        """Create a new instance of JournalEntry from an asyncpg.Record.

        Parameters
        ----------
        record : asyncpg.Record
            The record to create the instance from.

        Returns
        -------
        JournalEntry
            The created instance.
        """
        return cls(
            id=record["id"],
            user_id=hikari.Snowflake(record["user_id"]),
            guild_id=hikari.Snowflake(record["guild_id"]),
            content=record.get("content"),
            author_id=hikari.Snowflake(record["author_id"]) if record.get("author_id") else None,
            created_at=datetime.datetime.fromtimestamp(record["created_at"]),
            entry_type=JournalEntryType(record["entry_type"]),
        )

    @classmethod
    async def fetch(
        cls, id: int, user: hikari.SnowflakeishOr[hikari.PartialUser], guild: hikari.SnowflakeishOr[hikari.PartialGuild]
    ) -> t.Self | None:
        """Fetch a journal entry from the database.

        Parameters
        ----------
        id : int
            The ID of the journal entry.
        user : hikari.SnowflakeishOr[hikari.PartialUser]
            The user this entry belongs to.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild this entry belongs to.

        Returns
        -------
        Optional[JournalEntry]
            The journal entry from the database, if found.
        """
        record = await cls._db.fetchrow(
            "SELECT * FROM journal WHERE id = $1 AND user_id = $2 AND guild_id = $3",
            id,
            hikari.Snowflake(user),
            hikari.Snowflake(guild),
        )
        if not record or not record.get("id"):
            return None
        return cls.from_record(record)

    @classmethod
    async def fetch_journal(
        cls, user: hikari.SnowflakeishOr[hikari.PartialUser], guild: hikari.SnowflakeishOr[hikari.PartialGuild]
    ) -> list[t.Self]:
        """Fetch a user's journal from the database.

        Parameters
        ----------
        user : hikari.SnowflakeishOr[hikari.PartialUser]
            The user to fetch the journal for.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild this entry belongs to.

        Returns
        -------
        List[JournalEntry]
            The journal entries from the database sorted by creation date.
        """
        records = await cls._db.fetch(
            "SELECT * FROM journal WHERE user_id = $1 AND guild_id = $2 ORDER BY created_at DESC",
            hikari.Snowflake(user),
            hikari.Snowflake(guild),
        )
        return [cls.from_record(record) for record in records]

    async def update(self) -> None:
        """Update the journal entry in the database.

        If an entry with this ID does not yet exist, one will be created.

        If this entry doesn't have an ID, one will be assigned to it by the database.
        """
        if self.id is None:  # Entry doesn't yet exist, create a new one
            record = await self._db.fetchrow(
                """
                INSERT INTO journal (user_id, guild_id, content, author_id, created_at, entry_type)
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
                """,
                self.user_id,
                self.guild_id,
                self.content,
                self.author_id,
                self.created_at.timestamp(),
                self.entry_type.value,
            )
            assert record is not None
            self.id = record.get("id")
            return

        await self._db.execute(
            """
            INSERT INTO journal (id, user_id, guild_id, content, author_id, created_at, entry_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (id) DO
            UPDATE SET user_id = $2, guild_id = $3, content = $4, author_id = $5, created_at = $6,
            entry_type = $7
            """,
            self.id,
            self.user_id,
            self.guild_id,
            self.content,
            self.author_id,
            self.created_at.timestamp(),
            self.entry_type.value,
        )
