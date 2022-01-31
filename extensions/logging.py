import asyncio
import datetime
import json
import logging
from typing import Union, Optional, Dict, Any

import hikari
from hikari.audit_logs import AuditLog
from hikari.errors import ForbiddenError
import lightbulb

from models import SnedBot

user_logging = lightbulb.Plugin("Logging", include_datastore=True)

# Functions exposed to other extensions & plugins
user_logging.d.actions = {}

user_logging.d.valid_log_events = [
    "ban",
    "kick",
    "timeout",
    "message_delete",
    "message_delete_mod",
    "message_edit",
    "bulk_delete",
    "invites",
    "roles",
    "channels",
    "member_join",
    "member_leave",
    "nickname",
    "guild_settings",
    "warn",
]

# List of guilds where logging is temporarily suspended
user_logging.d.frozen_guilds = []


async def get_log_channel_id(log_event: str, guild_id: int) -> Optional[int]:

    if log_event not in user_logging.d.valid_log_events:
        raise ValueError("Invalid log_event passed.")

    records = await user_logging.app.db_cache.get(table="log_config", guild_id=guild_id)

    log_channels = json.loads(records[0]["log_channels"]) if records and records[0]["log_channels"] else None

    return log_channels[log_event] if log_channels and log_event in log_channels.keys() else None


user_logging.d.actions["get_log_channel_id"] = get_log_channel_id


async def get_log_channel_ids_view(guild_id: int) -> Dict[str, int]:
    """
    Return a mapping of log_event:channel_id
    """

    records = await user_logging.app.db_cache.get(table="log_config", guild_id=guild_id)

    log_channels = json.loads(records[0]["log_channels"]) if records and records[0]["log_channels"] else {}

    for log_event in user_logging.d.valid_log_events:
        if log_event not in log_channels.keys():
            log_channels[log_event] = None

    return log_channels


user_logging.d.actions["get_log_channel_ids_view"] = get_log_channel_ids_view


async def set_log_channel(log_event: str, guild_id: int, channel_id: Optional[int] = None) -> None:
    """Sets logging channel for a given logging event."""

    if log_event not in user_logging.d.valid_log_events:
        raise ValueError("Invalid log_event passed.")

    log_channels = await get_log_channel_ids_view(guild_id)
    log_channels[log_event] = channel_id
    await user_logging.app.pool.execute(
        """
        INSERT INTO log_config (log_channels, guild_id) VALUES ($1, $2)
        ON CONFLICT (guild_id) DO
        UPDATE SET log_channels = $1""",
        json.dumps(log_channels),
        guild_id,
    )
    await user_logging.app.db_cache.refresh(table="log_config", guild_id=guild_id)


user_logging.d.actions["set_log_channel"] = set_log_channel


async def log(
    log_event: str,
    log_content: Union[str, hikari.Embed],
    guild_id: int,
    file: Optional[hikari.File] = None,
    bypass: bool = False,
) -> None:
    """Log log_content into the channel assigned to log_event, if any."""

    if not user_logging.app.is_ready or not user_logging.app.db_cache.is_ready:
        return

    if guild_id in user_logging.d.frozen_guilds and not bypass:
        return

    log_channel_id = await get_log_channel_id(log_event, guild_id)

    if not log_channel_id:
        return

    if isinstance(log_content, hikari.Embed):
        log_content.timestamp = datetime.datetime.now(datetime.timezone.utc)
        embed = log_content
        content = hikari.UNDEFINED

    elif isinstance(log_content, str):
        content = log_content
        embed = hikari.UNDEFINED

    file = file if file else hikari.UNDEFINED

    # Check if the channel still exists or not, and lazily invalidate it if not
    log_channel = user_logging.app.cache.get_guild_channel(log_channel_id)
    if log_channel is None:
        return await set_log_channel(log_event, guild_id, None)

    try:
        await log_channel.send(content=content, embed=embed, file=file)
    except (hikari.ForbiddenError, hikari.HTTPError):
        return


user_logging.d.actions["log"] = log


async def freeze_logging(guild_id: int) -> None:
    """Call to temporarily suspend logging in the given guild. Useful if a log-spammy command is being executed."""
    if guild_id not in user_logging.d.frozen_guilds:
        user_logging.d.frozen_guilds.append(guild_id)


async def unfreeze_logging(guild_id: int) -> None:
    """Call to stop suspending the logging in a given guild."""
    await asyncio.sleep(5)  # For any pending actions, kinda crappy solution, but audit logs suck :/
    if guild_id in user_logging.d.frozen_guilds:
        user_logging.d.frozen_guilds.remove(guild_id)


async def find_auditlog_data(
    event: hikari.GuildEvent, *, type: hikari.AuditLogEventType, user_id: Optional[int] = hikari.UNDEFINED
) -> Optional[hikari.AuditLogEntry]:
    """Find a recently sent audit log entry that matches criteria.

    Parameters
    ----------
    event : hikari.GuildEvent
        The event that triggered this search.
    type : hikari.AuditLogEventType
        The type of audit log to look for.
    user_id : Optional[int], optional
        The user affected by this audit log, if any. By default hikari.UNDEFINED

    Returns
    -------
    Optional[hikari.AuditLogEntry]
        The entry, if found.

    Raises
    ------
    ValueError
        The passed event has no guild attached to it, or was not found in cache.
    """

    guild = event.get_guild()
    await asyncio.sleep(2.0)

    if not guild:
        raise ValueError("Cannot find guild to parse auditlogs for.")

    try:
        break_next = False
        async for entry in user_logging.app.rest.fetch_audit_log(guild, type=type):
            if break_next:
                break

            if user_id and user_id == entry.target_id:
                return entry
            elif user_id:
                break_next = True  # Only do two calls at max
                continue
            else:
                return entry

    except hikari.ForbiddenError:
        return


def create_log_content(message: hikari.Message, max_length: Optional[int] = None) -> str:
    contents = ""
    if message.attachments:
        contents = f"{contents}\n//The message contained one or more attachments."
    if message.embeds:
        contents = f"{contents}\n//The message contained one or more embeds."
    if not contents:  # idk how this is possible, but it somehow is sometimes
        contents = "//The message did not contain text."
    if max_length and len(contents) > max_length:
        return contents[: max_length - 3] + "..."

    return contents


@user_logging.listener(hikari.GuildMessageDeleteEvent, bind=True)
async def message_delete(event: hikari.GuildMessageDeleteEvent, plugin: lightbulb.Plugin) -> None:
    if not event.old_message or event.old_message.author.is_bot:
        return

    contents = create_log_content(event.old_message)

    entry = find_auditlog_data(event, type=hikari.AuditLogEventType.MESSAGE_DELETE, user_id=event.old_message.author.id)
    if entry:
        moderator: hikari.Member = plugin.app.cache.get_member(entry.user_id)
        embed = hikari.Embed(
            title=f"🗑️ Message deleted by Moderator",
            description=f"**Message author:** `{event.old_message.author} ({event.old_message.author.id})`\n**Moderator:** `{moderator} ({moderator.id})`\n**Channel:** {event.old_message.channel.mention}\n**Message content:** ```{contents}```",
            color=plugin.app.error_color,
        )
        await log("message_delete_mod", embed, event.guild_id)

    else:
        embed = hikari.Embed(
            title=f"🗑️ Message deleted",
            description=f"**Message author:** `{event.old_message.author} ({event.old_message.author.id})`\n**Channel:** {event.old_message.channel.mention}\n**Message content:** ```{contents}```",
            color=plugin.app.error_color,
        )
        await log("message_delete", embed, event.guild_id)


@user_logging.listener(hikari.GuildMessageUpdateEvent, bind=True)
async def message_update(event: hikari.GuildMessageUpdateEvent, plugin: lightbulb.Plugin) -> None:
    if not event.old_message or event.old_message.author.is_bot:
        return

    old_content = create_log_content(event.old_message, max_length=1800)
    new_content = create_log_content(event.message, max_length=1800)

    embed = hikari.Embed(
        title=f"🖊️ Message edited",
        description=f"**Message author:** `{event.author} ({event.author.id})`\n**Channel:** {event.get_channel().mention}\n**Before:** ```{old_content}``` \n**After:** ```{new_content}```\n[Jump!]({event.message.make_link(event.guild_id)})",
        color=plugin.app.embed_blue,
    )
    await log("message_edit", embed, event.guild_id)


@user_logging.listener(hikari.GuildBulkMessageDeleteEvent, bind=True)
async def bulk_message_delete(event: hikari.GuildBulkMessageDeleteEvent, plugin: lightbulb.Plugin) -> None:

    moderator = "Discord"
    entry = find_auditlog_data(event, type=hikari.AuditLogEventType.MESSAGE_BULK_DELETE)
    if entry:
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)

    embed = hikari.Embed(
        title=f"🗑️ Bulk message deletion",
        description=f"**Channel:** {event.get_channel().mention if event.get_channel() else 'Unknown'}\n**Moderator:** `{moderator}`\n```Multiple messages have been purged.```",
        color=plugin.app.error_color,
    )
    await log("bulk_delete", embed, event.guild_id)


# TODO: Log invites?


@user_logging.listener(hikari.RoleDeleteEvent, bind=True)
async def role_delete(event: hikari.RoleDeleteEvent) -> None:
    pass
