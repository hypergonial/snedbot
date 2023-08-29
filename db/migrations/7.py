from __future__ import annotations

import datetime
import logging
import re
import typing as t

import hikari
import lightbulb

from models import JournalEntry, JournalEntryType

if t.TYPE_CHECKING:
    from models.db import Database

NOTE_REGEX = re.compile(
    r"<t:(?P<timestamp>\d+):\w>: (?P<emoji>.+) \*\*(?P<verb>.+) (?:by|for) (?P<username>.+):\*\* (?P<content>.*)"
)

ENTRY_TYPES = {
    "Banned": JournalEntryType.BAN,
    "Unbanned": JournalEntryType.UNBAN,
    "Kicked": JournalEntryType.KICK,
    "Timed out": JournalEntryType.TIMEOUT,
    "Timeout removed": JournalEntryType.TIMEOUT_REMOVE,
    "Muted": JournalEntryType.TIMEOUT,  # Legacy
    "Unmuted": JournalEntryType.TIMEOUT_REMOVE,  # Legacy
    "Warned": JournalEntryType.WARN,
    "1 Warning removed": JournalEntryType.WARN_REMOVE,
    "Warnings cleared": JournalEntryType.WARN_CLEAR,
    "Note": JournalEntryType.NOTE,
}

logger = logging.getLogger(__name__)


def _parse_note(db: Database, user_id: int, guild_id: int, note: str) -> JournalEntry | None:
    match = NOTE_REGEX.match(note)
    if not match:
        logger.warning(f"Invalid note format:\n{note}")
        return

    users = db.app.cache.get_users_view()
    user: hikari.User | None = (
        lightbulb.utils.find(users.values(), lambda u: str(u) == match.group("username"))
        if match.group("username") != "Unknown"
        else None
    )
    timestamp = datetime.datetime.fromtimestamp(int(match.group("timestamp")))
    content: str | None = (
        match.group("content")
        if match.group("content")
        != "Error retrieving data from audit logs! Ensure the bot has permissions to view them!"
        else None
    )
    entry_type = ENTRY_TYPES[match.group("verb")]

    return JournalEntry(
        user_id=hikari.Snowflake(user_id),
        guild_id=hikari.Snowflake(guild_id),
        content=content,
        author_id=hikari.Snowflake(user) if user else None,
        created_at=timestamp,
        entry_type=entry_type,
    )


async def _migrate_notes(db: Database) -> None:
    logger.warning("Waiting for cache availability to start journal entry migration...")
    await db.app.wait_until_started()

    logger.warning("Migrating journal entries...")
    records = await db.fetch("SELECT * FROM users")

    for record in records:
        notes: list[str] = record.get("notes")
        user_id: int = record.get("user_id")
        guild_id: int = record.get("guild_id")
        if not notes:
            continue
        for note in notes:
            entry = _parse_note(db, user_id, guild_id, note)
            if entry:
                try:
                    await entry.update()
                except Exception as exc:
                    logger.error(f"Failed to migrate journal entry:\n{note}\n{exc}")

    await db.execute("ALTER TABLE users DROP COLUMN notes")
    logger.info("Journal entries migrated!")


async def run(db: Database) -> None:
    # Defer execution to after startup, don't block
    db._app.create_task(_migrate_notes(db))
