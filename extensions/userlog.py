from __future__ import annotations

import asyncio
import datetime
import enum
import json
import logging
import re
import sys
import traceback
import typing as t

import attr
import hikari
import lightbulb

from etc import const, get_perm_str
from models import SnedBot
from models.events import (
    AutoModMessageFlagEvent,
    MassBanEvent,
    RoleButtonCreateEvent,
    RoleButtonDeleteEvent,
    RoleButtonUpdateEvent,
    WarnCreateEvent,
    WarnRemoveEvent,
    WarnsClearEvent,
)
from models.journal import JournalEntry, JournalEntryType
from models.plugin import SnedPlugin
from utils import helpers

BOT_REASON_REGEX = re.compile(r"(?P<name>.*)\s\((?P<id>\d+)\):\s(?P<reason>.*)")
TIMEOUT_REGEX = re.compile(
    r"Timed out until (?P<date>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+\d{2}:\d{2}) - (?P<reason>.*)"
)

logger = logging.getLogger(__name__)

userlog = SnedPlugin("Logging", include_datastore=True)

# Functions exposed to other extensions & plugins
userlog.d.actions = lightbulb.utils.DataStore()

# Mapping of channel_id: payload
userlog.d.queue = {}

# Queue iter task
userlog.d._task = None


class LogEvent(enum.Enum):
    """Enum for all valid log events."""

    BAN = "ban"
    """Logs related to bans and unbans"""
    KICK = "kick"
    """Logs related to kicks"""
    TIMEOUT = "timeout"
    """Logs related to timeouts & timeout removals"""
    MESSAGE_DELETE = "message_delete"
    """Logs related to messages voluntarily deleted by users"""
    MESSAGE_DELETE_MOD = "message_delete_mod"
    """Logs related to messages deleted by moderators"""
    MESSAGE_EDIT = "message_edit"
    """Logs related to message edits"""
    BULK_DELETE = "bulk_delete"
    """Logs related to bulk message deletions by moderators"""
    FLAGS = "flags"
    """Logs related to automod message flagging"""
    ROLES = "roles"
    """Logs related to role creation, deletion updates & assignments"""
    CHANNELS = "channels"
    """Logs related to channel creation, deletion & updates"""
    MEMBER_JOIN = "member_join"
    """Logs related to member joins"""
    MEMBER_LEAVE = "member_leave"
    """Logs related to member leaves, this should not include kicks or bans"""
    NICKNAME = "nickname"
    """Logs related to nickname changes"""
    GUILD_SETTINGS = "guild_settings"
    """Logs related to guild setting changes"""
    WARN = "warn"
    """Logs related to new warnings, warning removals & clears"""


# List of guilds where logging is temporarily suspended
userlog.d.frozen_guilds = []


@attr.define()
class UserLike:
    """
    A wrapper for user-like objects, for easier printing
    """

    id: hikari.Snowflake
    username: str

    def __str__(self):
        return f"{self.username} ({self.id})"


@attr.define()
class ParsedBotReason:
    """
    A wrapper for parsing bot reasons following the format:

    <name> (<id>): <reason>
    """

    reason: str | None
    """The extracted reason string"""
    user: UserLike | None
    """The extracted UserLike object, this is the moderator who performed the action."""

    @classmethod
    def from_reason(cls, reason: str | None) -> ParsedBotReason:
        """
        Parse a reason string and return a StripBotReason object
        """
        match = BOT_REASON_REGEX.match(str(reason))

        if not match:
            return cls(reason, None)

        return cls(match.group("reason"), UserLike(hikari.Snowflake(match.group("id")), match.group("name")))


def display_user(user: hikari.UndefinedNoneOr[hikari.PartialUser | UserLike]) -> str:
    """
    A helper function for displaying user-like objects generically.
    """
    if not user:
        return "Unknown"

    if isinstance(user, UserLike):
        return str(user)

    return f"{user} ({user.id})"


async def get_log_channel_id(log_event: LogEvent, guild_id: int) -> int | None:
    """Get the channel ID for a given log event.

    Parameters
    ----------
    log_event : str
        The event to get the channel ID for.
    guild_id : int
        The ID of the guild.

    Returns
    -------
    int | None
        The channel ID, if any.

    Raises
    ------
    ValueError
        If an invalid log_event is passed.
    """
    records = await userlog.app.db_cache.get(table="log_config", guild_id=guild_id, limit=1)

    log_channels = json.loads(records[0]["log_channels"]) if records and records[0]["log_channels"] else None

    return log_channels.get(log_event.value) if log_channels else None


userlog.d.actions["get_log_channel_id"] = get_log_channel_id


async def get_log_channel_ids_view(guild_id: int) -> dict[str, int | None]:
    """
    Return a mapping of log_event:channel_id
    """

    records = await userlog.app.db_cache.get(table="log_config", guild_id=guild_id, limit=1)

    log_channels = json.loads(records[0]["log_channels"]) if records and records[0]["log_channels"] else {}

    for log_event in LogEvent:
        if log_event.value not in log_channels.keys():
            log_channels[log_event] = None

    return log_channels


userlog.d.actions["get_log_channel_ids_view"] = get_log_channel_ids_view


async def set_log_channel(log_event: LogEvent, guild_id: int, channel_id: int | None = None) -> None:
    """Sets logging channel for a given logging event."""
    log_channels = await get_log_channel_ids_view(guild_id)
    log_channels[log_event.value] = channel_id
    await userlog.app.db.execute(
        """
        INSERT INTO log_config (log_channels, guild_id) VALUES ($1, $2)
        ON CONFLICT (guild_id) DO
        UPDATE SET log_channels = $1""",
        json.dumps(log_channels),
        guild_id,
    )
    await userlog.app.db_cache.refresh(table="log_config", guild_id=guild_id)


userlog.d.actions["set_log_channel"] = set_log_channel


async def is_color_enabled(guild_id: int) -> bool:
    records = await userlog.app.db_cache.get(table="log_config", guild_id=guild_id, limit=1)
    return records[0]["color"] if records else True


userlog.d.actions["is_color_enabled"] = is_color_enabled


async def log(
    log_event: LogEvent,
    log_content: hikari.Embed,
    guild_id: int,
    file: hikari.UndefinedOr[hikari.Resourceish] = hikari.UNDEFINED,
    bypass: bool = False,
) -> None:
    """Log log_content into the channel assigned to log_event, if any.

    Parameters
    ----------
    log_event : str
        The channel associated with this event to post it under.
    log_content : hikari.Embed
        What needs to be logged.
    guild_id : int
        The ID of the guild.
    file : Optional[hikari.File], optional
        An attachment, if any, by default None
    bypass : bool, optional
        If bypassing guild log freeze is desired, by default False
    """
    if not userlog.app.is_ready or not userlog.app.db_cache.is_ready:
        return

    if guild_id in userlog.d.frozen_guilds and not bypass:
        return

    log_channel_id = await get_log_channel_id(log_event, guild_id)

    if not log_channel_id:
        return

    log_content.timestamp = datetime.datetime.now(datetime.timezone.utc)
    embed = log_content

    # Check if the channel still exists or not, and lazily invalidate it if not
    log_channel = userlog.app.cache.get_guild_channel(log_channel_id)
    if log_channel is None:
        return await set_log_channel(log_event, guild_id, None)
    assert isinstance(log_channel, hikari.TextableGuildChannel)

    me = userlog.app.cache.get_member(guild_id, userlog.app.user_id)
    assert me is not None
    perms = lightbulb.utils.permissions_in(log_channel, me)
    if not (perms & hikari.Permissions.SEND_MESSAGES) or not (perms & hikari.Permissions.EMBED_LINKS):
        # Do not attempt message send if we have no perms
        return

    if file:  # Embeds with attachments will be sent without grouping
        try:
            await log_channel.send(embed=embed, attachment=file)
            return
        except (hikari.ForbiddenError, hikari.HTTPError, asyncio.TimeoutError):
            return

    if userlog.d.queue.get(log_channel.id) is None:
        userlog.d.queue[log_channel.id] = []

    userlog.d.queue[log_channel.id].append(embed)


userlog.d.actions["log"] = log


async def _iter_queue() -> None:
    """Iter queue and bulk-send embeds"""
    try:
        while True:
            for channel_id, embeds in userlog.d.queue.items():
                if not embeds:
                    continue

                embed_chunks: list[list[hikari.Embed]] = [[]]
                for embed in embeds:
                    # If combined length of all embeds is below 6000 and there are less than 10 embeds in chunk, add to chunk
                    if (
                        sum([embed.total_length() for embed in embed_chunks[-1]]) + embed.total_length()
                    ) <= 6000 and len(embed_chunks[-1]) < 10:
                        embed_chunks[-1].append(embed)
                    # Otherwise make new chunk
                    else:
                        embed_chunks.append([embed])

                for chunk in embed_chunks:
                    try:
                        await userlog.app.rest.create_message(channel_id, embeds=chunk)
                    except Exception as exc:
                        logger.warning(f"Failed to send log embed chunk to channel {channel_id}: {exc}")

                userlog.d.queue[channel_id] = []

            await asyncio.sleep(10.0)

    except Exception as error:
        print("Encountered exception in userlog queue iteration:", error)
        traceback.print_exception(error.__class__, error, error.__traceback__, file=sys.stderr)


async def freeze_logging(guild_id: int) -> None:
    """Call to temporarily suspend logging in the given guild. Useful if a log-spammy command is being executed."""
    if guild_id not in userlog.d.frozen_guilds:
        userlog.d.frozen_guilds.append(guild_id)


userlog.d.actions["freeze_logging"] = freeze_logging


async def unfreeze_logging(guild_id: int) -> None:
    """Call to stop suspending the logging in a given guild."""
    await asyncio.sleep(5)  # For any pending actions, kinda crappy solution, but audit logs suck :/
    if guild_id in userlog.d.frozen_guilds:
        userlog.d.frozen_guilds.remove(guild_id)


userlog.d.actions["unfreeze_logging"] = unfreeze_logging


async def find_auditlog_data(
    guild: hikari.SnowflakeishOr[hikari.PartialGuild],
    *,
    event_type: hikari.AuditLogEventType,
    user_id: int | None = None,
) -> hikari.AuditLogEntry | None:
    """Find a recently sent audit log entry that matches criteria.

    Parameters
    ----------
    event : hikari.Event
        The event that triggered this search.
    event_type : hikari.AuditLogEventType
        The type of audit log entry to look for.
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

    # Stuff that is observed to just take too goddamn long to appear in AuditLogs
    takes_an_obscene_amount_of_time = [hikari.AuditLogEventType.MESSAGE_BULK_DELETE]

    sleep_time = 5.0 if event_type not in takes_an_obscene_amount_of_time else 10.0
    await asyncio.sleep(sleep_time)  # Wait for auditlog event to hopefully arrive

    return userlog.app.audit_log_cache.get_first_by(
        guild,
        event_type,
        lambda e: (e.target_id == user_id if user_id else True)
        and e.id.created_at > helpers.utcnow() - datetime.timedelta(seconds=15),
    )


async def get_perms_diff(old_role: hikari.Role, role: hikari.Role) -> str | None:
    """
    A helper function for displaying role updates.
    Returns a string containing the differences between two roles.
    """

    old_perms = old_role.permissions
    new_perms = role.permissions
    perms_diff = ""
    is_colored = await is_color_enabled(role.guild_id)
    gray = "[1;30m" if is_colored else ""
    white = "[0;37m" if is_colored else ""
    red = "[1;31m" if is_colored else ""
    green = "[1;32m" if is_colored else ""
    reset = "[0m" if is_colored else ""

    for perm in hikari.Permissions:
        if (old_perms & perm) == (new_perms & perm):
            continue

        old_state = f"{green}Allow" if (old_perms & perm) else f"{red}Deny"
        new_state = f"{green}Allow" if (new_perms & perm) else f"{red}Deny"

        perms_diff = f"{perms_diff}\n   {white}{get_perm_str(perm)}: {old_state} {gray}-> {new_state}"

    return perms_diff.strip() + reset if perms_diff.strip() else None


T = t.TypeVar("T")


async def get_diff(guild_id: int, old_object: T, object: T, attrs: dict[str, str]) -> str | None:
    """
    A helper function for displaying differences between certain attributes
    Returns a formatted string containing the differences.
    The two objects are expected to share the same attributes.
    """
    diff = ""

    is_colored = await is_color_enabled(guild_id)
    gray = "[1;30m" if is_colored else ""
    white = "[0;37m" if is_colored else ""
    red = "[1;31m" if is_colored else ""
    green = "[1;32m" if is_colored else ""
    reset = "[0m" if is_colored else ""

    for attribute in attrs.keys():
        old = getattr(old_object, attribute, hikari.UNDEFINED)
        new = getattr(object, attribute, hikari.UNDEFINED)

        if hasattr(old, "name") and hasattr(new, "name"):  # Handling flags enums
            diff = (
                f"{diff}\n{white}{attrs[attribute]}: {red}{old.name} {gray}-> {green}{new.name}" if old != new else diff
            )
        elif isinstance(old, datetime.timedelta) and isinstance(new, datetime.timedelta):  # Handling timedeltas
            diff = (
                f"{diff}\n{white}{attrs[attribute]}: {red}{old.total_seconds()} {gray}-> {green}{new.total_seconds()}"
                if old != new
                else diff
            )
        elif (
            isinstance(old, list)
            and isinstance(new, list)
            and (old and hasattr(old[0], "name") or new and hasattr(new[0], "name"))
        ):  # Handling flag lists
            old_names = [str(x) for x in old]
            new_names = [str(x) for x in new]
            if not set(old_names) - set(new_names) or not set(new_names) - set(old_names):
                continue

            diff = (
                f"{diff}\n{white}{attrs[attribute]}: {red}{', '.join(old_names)} {gray}-> {green}{', '.join(new_names)}"
                if old != new
                else diff
            )
        else:
            diff = f"{diff}\n{white}{attrs[attribute]}: {red}{old} {gray}-> {green}{new}" if old != new else diff

    return diff.strip() + reset if diff.strip() else None


def create_log_content(message: hikari.PartialMessage, max_length: int | None = None) -> str:
    """
    Process missing-content markers for messages before sending to logs
    """
    contents = message.content
    if message.attachments:
        contents = f"{contents}\n//The message contained one or more attachments."
    if message.embeds:
        contents = f"{contents}\n//The message contained one or more embeds."
    if not contents:  # idk how this is possible, but it somehow is sometimes
        contents = "//The message did not contain text."
    if max_length and len(contents) > max_length:
        return contents[: max_length - 3] + "..."

    return contents


###############################
#                             #
# Event Listeners start below #
#                             #
###############################


@userlog.listener(hikari.GuildMessageDeleteEvent, bind=True)
async def message_delete(plugin: SnedPlugin, event: hikari.GuildMessageDeleteEvent) -> None:
    if not event.old_message or event.old_message.author.is_bot:
        return

    contents = create_log_content(event.old_message)

    entry = await find_auditlog_data(
        event.guild_id, event_type=hikari.AuditLogEventType.MESSAGE_DELETE, user_id=event.old_message.author.id
    )

    if entry:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)

        embed = hikari.Embed(
            title="🗑️ Message deleted by Moderator",
            description=f"""**Message author:** `{display_user(event.old_message.author)}`
**Moderator:** `{display_user(moderator)}`
**Channel:** <#{event.channel_id}>
**Message content:** ```{contents.replace("`", "´")}```""",
            color=const.ERROR_COLOR,
        )
        await log(LogEvent.MESSAGE_DELETE_MOD, embed, event.guild_id)

    else:
        embed = hikari.Embed(
            title="🗑️ Message deleted",
            description=f"""**Message author:** `{display_user(event.old_message.author)}`
**Channel:** <#{event.channel_id}>
**Message content:** ```{contents.replace("`", "´")}```""",
            color=const.ERROR_COLOR,
        )
        await log(LogEvent.MESSAGE_DELETE, embed, event.guild_id)


@userlog.listener(hikari.GuildMessageUpdateEvent, bind=True)
async def message_update(plugin: SnedPlugin, event: hikari.GuildMessageUpdateEvent) -> None:
    if (
        not event.old_message
        or event.old_message.author is hikari.UNDEFINED
        or event.message.author is hikari.UNDEFINED
        or event.old_message.author.is_bot
    ):
        return

    if (event.old_message.flags and not hikari.MessageFlag.CROSSPOSTED & event.old_message.flags) and (
        event.message.flags and hikari.MessageFlag.CROSSPOSTED & event.message.flags
    ):
        return

    assert event.old_message and event.message

    old_content = create_log_content(event.old_message, max_length=1800)
    new_content = create_log_content(event.message, max_length=1800)

    embed = hikari.Embed(
        title="🖊️ Message edited",
        description=f"""**Message author:** `{display_user(event.author)}`
**Channel:** <#{event.channel_id}>
**Before:** ```{old_content.replace("`", "´")}``` \n**After:** ```{new_content.replace("`", "´")}```
[Jump!]({event.message.make_link(event.guild_id)})""",
        color=const.EMBED_BLUE,
    )
    await log(LogEvent.MESSAGE_EDIT, embed, event.guild_id)


@userlog.listener(hikari.GuildBulkMessageDeleteEvent, bind=True)
async def bulk_message_delete(plugin: SnedPlugin, event: hikari.GuildBulkMessageDeleteEvent) -> None:
    moderator = None
    entry = await find_auditlog_data(event.guild_id, event_type=hikari.AuditLogEventType.MESSAGE_BULK_DELETE)
    if entry:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)

    channel = event.get_channel()

    embed = hikari.Embed(
        title="🗑️ Bulk message deletion",
        description=f"""**Channel:** {channel.mention if channel else 'Unknown'}
**Moderator:** `{display_user(moderator) if moderator else 'Discord'}`
```{len(event.message_ids)} messages have been purged.```""",
        color=const.ERROR_COLOR,
    )
    await log(LogEvent.BULK_DELETE, embed, event.guild_id)


@userlog.listener(hikari.RoleDeleteEvent, bind=True)
async def role_delete(plugin: SnedPlugin, event: hikari.RoleDeleteEvent) -> None:
    entry = await find_auditlog_data(event.guild_id, event_type=hikari.AuditLogEventType.ROLE_DELETE)
    if entry and event.old_role:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title="🗑️ Role deleted",
            description=f"**Role:** `{event.old_role}`\n**Moderator:** `{display_user(moderator)}`",
            color=const.ERROR_COLOR,
        )
        await log(LogEvent.ROLES, embed, event.guild_id)


@userlog.listener(hikari.RoleCreateEvent, bind=True)
async def role_create(plugin: SnedPlugin, event: hikari.RoleCreateEvent) -> None:
    entry = await find_auditlog_data(event.guild_id, event_type=hikari.AuditLogEventType.ROLE_CREATE)
    if entry and event.role:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title="❇️ Role created",
            description=f"**Role:** `{event.role}`\n**Moderator:** `{display_user(moderator)}`",
            color=const.EMBED_GREEN,
        )
        await log(LogEvent.ROLES, embed, event.guild_id)


@userlog.listener(hikari.RoleUpdateEvent, bind=True)
async def role_update(plugin: SnedPlugin, event: hikari.RoleUpdateEvent) -> None:
    entry = await find_auditlog_data(event.guild_id, event_type=hikari.AuditLogEventType.ROLE_UPDATE)
    if entry and event.old_role:
        assert entry.user_id
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)

        attrs = {
            "name": "Name",
            "position": "Position",
            "is_hoisted": "Hoisted",
            "is_mentionable": "Mentionable",
            "color": "Color",
            "icon_hash": "Icon Hash",
            "unicode_emoji": "Unicode Emoji",
        }
        diff = await get_diff(event.guild_id, event.old_role, event.role, attrs)
        perms_diff = await get_perms_diff(event.old_role, event.role)
        if not diff and not perms_diff:
            diff = "Changes could not be resolved."

        perms_str = f"\nPermissions:\n {perms_diff}" if perms_diff else ""
        embed = hikari.Embed(
            title="🖊️ Role updated",
            description=f"""**Role:** `{event.role.name}` \n**Moderator:** `{display_user(moderator)}`\n**Changes:**```ansi\n{diff}{perms_str}```""",
            color=const.EMBED_BLUE,
        )
        await log(LogEvent.ROLES, embed, event.guild_id)


@userlog.listener(hikari.GuildChannelDeleteEvent, bind=True)
async def channel_delete(plugin: SnedPlugin, event: hikari.GuildChannelDeleteEvent) -> None:
    entry = await find_auditlog_data(event.guild_id, event_type=hikari.AuditLogEventType.CHANNEL_DELETE)
    if entry and event.channel:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title="#️⃣ Channel deleted",
            description=f"**Channel:** `{event.channel.name}` `({event.channel.type.name})`\n**Moderator:** `{display_user(moderator)}`",  # type: ignore
            color=const.ERROR_COLOR,
        )
        await log(LogEvent.CHANNELS, embed, event.guild_id)


@userlog.listener(hikari.GuildChannelCreateEvent, bind=True)
async def channel_create(plugin: SnedPlugin, event: hikari.GuildChannelCreateEvent) -> None:
    entry = await find_auditlog_data(event.guild_id, event_type=hikari.AuditLogEventType.CHANNEL_CREATE)
    if entry and event.channel:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title="#️⃣ Channel created",
            description=f"**Channel:** {event.channel.mention} `({event.channel.type.name})`\n**Moderator:** `{display_user(moderator)}`",  # type: ignore
            color=const.EMBED_GREEN,
        )
        await log(LogEvent.CHANNELS, embed, event.guild_id)


@userlog.listener(hikari.GuildChannelUpdateEvent, bind=True)
async def channel_update(plugin: SnedPlugin, event: hikari.GuildChannelUpdateEvent) -> None:
    entry = await find_auditlog_data(event.guild_id, event_type=hikari.AuditLogEventType.CHANNEL_UPDATE)

    if entry and event.old_channel:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)

        if moderator and moderator.is_bot:  # Ignore bots updating channels
            return

        attrs = {
            "name": "Name",
            "position": "Position",
            "parent_id": "Category",
        }
        if isinstance(event.channel, hikari.TextableGuildChannel):
            attrs["topic"] = "Topic"
            attrs["is_nsfw"] = "Is NSFW"

        if isinstance(event.channel, hikari.GuildTextChannel):
            attrs["rate_limit_per_user"] = "Slowmode duration"

        if isinstance(event.channel, (hikari.GuildVoiceChannel, hikari.GuildStageChannel)):
            attrs["bitrate"] = "Bitrate"
            attrs["region"] = "Region"
            attrs["user_limit"] = "User limit"
        if isinstance(event.channel, hikari.GuildVoiceChannel):
            attrs["video_quality_mode"] = "Video Quality"

        diff = await get_diff(event.guild_id, event.old_channel, event.channel, attrs)

        # Because displaying this nicely is practically impossible
        if event.old_channel.permission_overwrites != event.channel.permission_overwrites:
            diff = f"{diff}\nChannel overrides have been modified."

        diff = diff or "Changes could not be resolved."

        embed = hikari.Embed(
            title="#️⃣ Channel updated",
            description=f"Channel {event.channel.mention} was updated by `{display_user(moderator)}`.\n**Changes:**\n```ansi\n{diff}```",
            color=const.EMBED_BLUE,
        )
        await log(LogEvent.CHANNELS, embed, event.guild_id)


@userlog.listener(hikari.GuildUpdateEvent, bind=True)
async def guild_update(plugin: SnedPlugin, event: hikari.GuildUpdateEvent) -> None:
    entry = await find_auditlog_data(event.guild_id, event_type=hikari.AuditLogEventType.GUILD_UPDATE)

    moderator = None
    if event.old_guild:
        if entry:
            assert entry.user_id is not None
            moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)

        if (
            event.old_guild.premium_subscription_count != event.guild.premium_subscription_count
            and event.old_guild.premium_tier == event.guild.premium_tier
        ):
            # If someone boosted but there was no tier change, ignore
            return

        attrs = {
            "name": "Name",
            "icon_url": "Icon URL",
            "features": "Features",
            "afk_channel_id": "AFK Channel",
            "afk_timeout": "AFK Timeout",
            "banner_url": "Banner URL",
            "default_message_notifications": "Default Notification Level",
            "description": "Description",
            "discovery_splash_hash": "Discovery Splash",
            "explicit_content_filter": "Explicit Content Filter",
            "is_widget_enabled": "Widget Enabled",
            "banner_hash": "Banner",
            "mfa_level": "MFA Level",
            "owner_id": "Owner ID",
            "preferred_locale": "Locale",
            "premium_tier": "Nitro Tier",
            "public_updates_channel_id": "Public Updates Channel",
            "rules_channel_id": "Rules Channel",
            "splash_hash": "Splash",
            "system_channel_id": "System Channel",
            "system_channel_flags": "System Channel Flags",
            "vanity_url_code": "Vanity URL",
            "verification_level": "Verification Level",
            "widget_channel_id": "Widget channel",
            "nsfw_level": "NSFW Level",
        }
        diff = await get_diff(event.guild_id, event.old_guild, event.guild, attrs)
        diff = diff or "Changes could not be resolved."

        embed = hikari.Embed(
            title="🖊️ Guild updated",
            description=f"Guild settings have been updated by `{display_user(moderator)}`.\n**Changes:**\n```ansi\n{diff}```",
            color=const.EMBED_BLUE,
        )
        await log(LogEvent.GUILD_SETTINGS, embed, event.guild_id)


@userlog.listener(hikari.BanDeleteEvent, bind=True)
async def member_ban_remove(plugin: SnedPlugin, event: hikari.BanDeleteEvent) -> None:
    entry = await find_auditlog_data(
        event.guild_id, event_type=hikari.AuditLogEventType.MEMBER_BAN_REMOVE, user_id=event.user.id
    )
    if entry:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        reason: str | None = entry.reason or "No reason provided"
    else:
        moderator = None
        reason = "Unable to view audit logs! Please ensure the bot has the necessary permissions to view them!"

    if isinstance(moderator, hikari.Member) and moderator.id == plugin.app.user_id:
        parsed = ParsedBotReason.from_reason(reason)
        reason, moderator = (parsed.reason, parsed.user)
        moderator = parsed.user or plugin.app.get_me()

    embed = hikari.Embed(
        title="🔨 User unbanned",
        description=f"**Offender:** `{display_user(event.user)}`\n**Moderator:** `{display_user(moderator)}`\n**Reason:** ```{reason}```",
        color=const.EMBED_GREEN,
    )
    await log(LogEvent.BAN, embed, event.guild_id)

    await JournalEntry(
        user_id=event.user.id,
        guild_id=event.guild_id,
        entry_type=JournalEntryType.UNBAN,
        content=reason,
        author_id=moderator.id if isinstance(moderator, (UserLike, hikari.PartialUser)) else None,
        created_at=helpers.utcnow(),
    ).update()


@userlog.listener(hikari.BanCreateEvent, bind=True)
async def member_ban_add(plugin: SnedPlugin, event: hikari.BanCreateEvent) -> None:
    entry = await find_auditlog_data(
        event.guild_id, event_type=hikari.AuditLogEventType.MEMBER_BAN_ADD, user_id=event.user.id
    )
    if entry:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        reason: str | None = entry.reason or "No reason provided"
    else:
        moderator = None
        reason = "Unable to view audit logs! Please ensure the bot has the necessary permissions to view them!"

    if isinstance(moderator, hikari.Member) and moderator.id == plugin.app.user_id:
        parsed = ParsedBotReason.from_reason(reason)
        reason, moderator = (parsed.reason, parsed.user)
        moderator = moderator or plugin.app.get_me()

    embed = hikari.Embed(
        title="🔨 User banned",
        description=f"**Offender:** `{display_user(event.user)}`\n**Moderator: **`{display_user(moderator)}`\n**Reason:**```{reason}```",
        color=const.ERROR_COLOR,
    )
    await log(LogEvent.BAN, embed, event.guild_id)

    await JournalEntry(
        user_id=event.user.id,
        guild_id=event.guild_id,
        entry_type=JournalEntryType.BAN,
        content=reason,
        author_id=moderator.id if isinstance(moderator, (UserLike, hikari.PartialUser)) else None,
        created_at=helpers.utcnow(),
    ).update()


@userlog.listener(hikari.MemberDeleteEvent, bind=True)
async def member_delete(plugin: SnedPlugin, event: hikari.MemberDeleteEvent) -> None:
    if event.user_id == plugin.app.user_id:
        return  # RIP

    entry = await find_auditlog_data(
        event.guild_id, event_type=hikari.AuditLogEventType.MEMBER_KICK, user_id=event.user.id
    )

    if entry:  # This is a kick
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        reason: str | None = entry.reason or "No reason provided"

        if isinstance(moderator, hikari.Member) and moderator.id == plugin.app.user_id:
            parsed = ParsedBotReason.from_reason(reason)
            reason, moderator = (parsed.reason, parsed.user)
            moderator = moderator or plugin.app.get_me()

        embed = hikari.Embed(
            title="🚪👈 User was kicked",
            description=f"**Offender:** `{display_user(event.user)}`\n**Moderator:**`{display_user(moderator)}`\n**Reason:**```{reason}```",
            color=const.ERROR_COLOR,
        )
        await log(LogEvent.KICK, embed, event.guild_id)

        await JournalEntry(
            user_id=event.user.id,
            guild_id=event.guild_id,
            entry_type=JournalEntryType.KICK,
            content=reason,
            author_id=moderator.id if isinstance(moderator, (UserLike, hikari.PartialUser)) else None,
            created_at=helpers.utcnow(),
        ).update()
        return

    embed = hikari.Embed(
        title="🚪 User left",
        description=f"**User:** `{display_user(event.user)}`\n**User count:** `{len(plugin.app.cache.get_members_view_for_guild(event.guild_id))}`",
        color=const.ERROR_COLOR,
    ).set_thumbnail(event.user.display_avatar_url)
    await log(LogEvent.MEMBER_LEAVE, embed, event.guild_id)


@userlog.listener(hikari.MemberCreateEvent, bind=True)
async def member_create(plugin: SnedPlugin, event: hikari.MemberCreateEvent) -> None:
    embed = (
        hikari.Embed(
            title="🚪 User joined",
            description=f"**User:** `{display_user(event.member)}`\n**User count:** `{len(plugin.app.cache.get_members_view_for_guild(event.guild_id))}`",
            color=const.EMBED_GREEN,
        )
        .add_field(
            name="Account created",
            value=f"{helpers.format_dt(event.member.created_at)} ({helpers.format_dt(event.member.created_at, style='R')})",
            inline=False,
        )
        .set_thumbnail(event.member.display_avatar_url)
    )
    await log(LogEvent.MEMBER_JOIN, embed, event.guild_id)


@userlog.listener(hikari.MemberUpdateEvent, bind=True)
async def member_update(plugin: SnedPlugin, event: hikari.MemberUpdateEvent) -> None:
    if not event.old_member:
        return

    old_member = event.old_member
    member = event.member

    if old_member.communication_disabled_until() != member.communication_disabled_until():
        """Timeout logging"""
        comms_disabled_until = member.communication_disabled_until()

        entry = await find_auditlog_data(
            event.guild_id, event_type=hikari.AuditLogEventType.MEMBER_UPDATE, user_id=event.user.id
        )
        if not entry:
            return

        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)

        # Reason parsing
        if entry.user_id == plugin.app.user_id and entry.reason:
            # Find actual moderator instead of bot
            parsed = ParsedBotReason.from_reason(entry.reason)
            moderator = parsed.user or plugin.app.get_me()
            reason = parsed.reason or "No reason provided"

            # Ignore re-timeouts
            if reason.startswith("Automatic timeout extension applied"):
                return

            # In the case of bot timeouts, they might last longer than a month
            # with re-timeouts, so we need to parse the actual date from the remaining reason
            if match := TIMEOUT_REGEX.match(reason):
                comms_disabled_until = datetime.datetime.fromisoformat(match.group("date"))
                reason = match.group("reason")
        else:
            reason = entry.reason or "No reason provided"

        if comms_disabled_until is None:
            embed = hikari.Embed(
                title="🔉 User timeout removed",
                description=f"**User:** `{display_user(member)}` \n**Moderator:** `{display_user(moderator)}` \n**Reason:** ```{reason}```",
                color=const.EMBED_GREEN,
            )
            await log(LogEvent.TIMEOUT, embed, event.guild_id)

            await JournalEntry(
                user_id=event.user.id,
                guild_id=event.guild_id,
                entry_type=JournalEntryType.TIMEOUT_REMOVE,
                content=reason,
                author_id=moderator.id if moderator else None,
                created_at=helpers.utcnow(),
            ).update()
            return

        assert comms_disabled_until is not None

        embed = hikari.Embed(
            title="🔇 User timed out",
            description=f"""**User:** `{display_user(member)}`
**Moderator:** `{display_user(moderator)}`
**Until:** {helpers.format_dt(comms_disabled_until)} ({helpers.format_dt(comms_disabled_until, style='R')})
**Reason:** ```{reason}```""",
            color=const.ERROR_COLOR,
        )

        await JournalEntry(
            user_id=event.user.id,
            guild_id=event.guild_id,
            entry_type=JournalEntryType.TIMEOUT,
            content=f"Until {helpers.format_dt(comms_disabled_until, style='d')} - {reason}",
            author_id=moderator.id if moderator else None,
            created_at=helpers.utcnow(),
        ).update()

        await log(LogEvent.TIMEOUT, embed, event.guild_id)

    elif old_member.nickname != member.nickname:
        """Nickname change handling"""
        embed = hikari.Embed(
            title="🖊️ Nickname changed",
            description=f"**User:** `{display_user(member)}`\nNickname before: `{old_member.nickname}`\nNickname after: `{member.nickname}`",
            color=const.EMBED_BLUE,
        )
        await log(LogEvent.NICKNAME, embed, event.guild_id)

    elif old_member.role_ids != member.role_ids:
        # Check difference in roles between the two
        add_diff = list(set(member.role_ids) - set(old_member.role_ids))
        rem_diff = list(set(old_member.role_ids) - set(member.role_ids))

        if not add_diff and not rem_diff:
            # No idea why this is needed, but otherwise I get empty role updates
            return

        role = userlog.app.cache.get_role(add_diff[0]) if add_diff else userlog.app.cache.get_role(rem_diff[0])

        if role and role.is_managed:  # Do not handle roles managed by bots & other integration stuff
            return

        entry = await find_auditlog_data(
            event.guild_id, event_type=hikari.AuditLogEventType.MEMBER_ROLE_UPDATE, user_id=event.user.id
        )

        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry and entry.user_id else None

        if moderator is None:
            return

        if entry and entry.user_id == plugin.app.user_id:
            # Attempt to find the moderator in reason if sent by us
            moderator = ParsedBotReason.from_reason(entry.reason).user or plugin.app.get_me()

        if isinstance(moderator, (hikari.User)) and moderator.is_bot:
            # Do not log role updates done by ourselves or other bots
            # Provided that the role was not added through /role
            return

        if add_diff:
            embed = hikari.Embed(
                title="🖊️ Member roles updated",
                description=f"**User:** `{display_user(member)}`\n**Moderator:** `{display_user(moderator)}`\n**Role added:** <@&{add_diff[0]}>",
                color=const.EMBED_BLUE,
            )
            await log(LogEvent.ROLES, embed, event.guild_id)

        elif rem_diff:
            embed = hikari.Embed(
                title="🖊️ Member roles updated",
                description=f"**User:** `{display_user(member)}`\n**Moderator:** `{display_user(moderator)}`\n**Role removed:** <@&{rem_diff[0]}>",
                color=const.EMBED_BLUE,
            )
            await log(LogEvent.ROLES, embed, event.guild_id)


@userlog.listener(WarnCreateEvent, bind=True)
async def warn_create(plugin: SnedPlugin, event: WarnCreateEvent) -> None:
    embed = hikari.Embed(
        title="⚠️ Warning issued",
        description=f"**Offender:** `{display_user(event.member)}`\n**Moderator:** `{display_user(event.moderator)}`\n**Warns:** {event.warn_count}\n**Reason:** ```{event.reason}```",
        color=const.WARN_COLOR,
    )

    await log(LogEvent.WARN, embed, event.guild_id)

    await JournalEntry(
        user_id=event.member.id,
        guild_id=event.guild_id,
        entry_type=JournalEntryType.WARN,
        content=event.reason,
        author_id=hikari.Snowflake(event.moderator),
        created_at=helpers.utcnow(),
    ).update()


@userlog.listener(WarnRemoveEvent, bind=True)
async def warn_remove(plugin: SnedPlugin, event: WarnRemoveEvent) -> None:
    embed = hikari.Embed(
        title="⚠️ Warning removed",
        description=f"**Recipient:** `{display_user(event.member)}`\n**Moderator:** `{display_user(event.moderator)}`\n**Warns:** {event.warn_count}\n**Reason:** ```{event.reason}```",
        color=const.EMBED_GREEN,
    )

    await log(LogEvent.WARN, embed, event.guild_id)

    await JournalEntry(
        user_id=event.member.id,
        guild_id=event.guild_id,
        entry_type=JournalEntryType.WARN_REMOVE,
        content=event.reason,
        author_id=hikari.Snowflake(event.moderator),
        created_at=helpers.utcnow(),
    ).update()


@userlog.listener(WarnsClearEvent, bind=True)
async def warns_clear(plugin: SnedPlugin, event: WarnsClearEvent) -> None:
    embed = hikari.Embed(
        title="⚠️ Warnings cleared",
        description=f"**Recipient:** `{display_user(event.member)}`\n**Moderator:** `{display_user(event.moderator)}`\n**Warns:** {event.warn_count}\n**Reason:** ```{event.reason}```",
        color=const.EMBED_GREEN,
    )

    await log(LogEvent.WARN, embed, event.guild_id)

    await JournalEntry(
        user_id=event.member.id,
        guild_id=event.guild_id,
        entry_type=JournalEntryType.WARN_CLEAR,
        content=event.reason,
        author_id=hikari.Snowflake(event.moderator),
        created_at=helpers.utcnow(),
    ).update()


@userlog.listener(AutoModMessageFlagEvent, bind=True)
async def flag_message(plugin: SnedPlugin, event: AutoModMessageFlagEvent) -> None:
    user_id = hikari.Snowflake(event.user)

    reason = helpers.format_reason(event.reason, max_length=1500)

    user = (
        event.user
        if isinstance(event.user, hikari.PartialUser)
        else (plugin.app.cache.get_member(event.guild_id, user_id) or (await plugin.app.rest.fetch_user(user_id)))
    )
    content = (
        helpers.format_reason(event.message.content, max_length=2000) if event.message.content else "No content found."
    )

    embed = hikari.Embed(
        title="❗🚩 Message flagged",
        description=f"`{display_user(user)}` was flagged by auto-moderator for suspicious behaviour.\n**Reason:**```{reason}```\n**Content:** ```{content}```\n\n[Jump to message!]({event.message.make_link(event.guild_id)})",
        color=const.ERROR_COLOR,
    )
    await log(LogEvent.FLAGS, embed, event.guild_id)


@userlog.listener(MassBanEvent)
async def massban_execute(event: MassBanEvent) -> None:
    log_embed = hikari.Embed(
        title="🔨 Massban concluded",
        description=f"Banned **{event.successful}/{event.total}** users.\n**Moderator:** `{display_user(event.moderator)}`\n**Reason:** ```{event.reason}```",
        color=const.ERROR_COLOR,
    )
    await log(LogEvent.BAN, log_embed, event.guild_id, file=event.logfile, bypass=True)


@userlog.listener(RoleButtonCreateEvent)
async def rolebutton_create(event: RoleButtonCreateEvent) -> None:
    log_embed = hikari.Embed(
        title="❇️ Rolebutton Added",
        description=f"**ID:** {event.rolebutton.id}\n**Channel:** <#{event.rolebutton.channel_id}>\n**Role:** <@&{event.rolebutton.role_id}>\n**Moderator:** `{display_user(event.moderator)}`",
        color=const.EMBED_GREEN,
    )
    await log(LogEvent.ROLES, log_embed, event.guild_id)


@userlog.listener(RoleButtonDeleteEvent)
async def rolebutton_delete(event: RoleButtonDeleteEvent) -> None:
    log_embed = hikari.Embed(
        title="🗑️ Rolebutton Deleted",
        description=f"**ID:** {event.rolebutton.id}\n**Channel:** <#{event.rolebutton.channel_id}>\n**Role:** <@&{event.rolebutton.role_id}>\n**Moderator:** `{display_user(event.moderator)}`",
        color=const.ERROR_COLOR,
    )
    await log(LogEvent.ROLES, log_embed, event.guild_id)


@userlog.listener(RoleButtonUpdateEvent)
async def rolebutton_update(event: RoleButtonUpdateEvent) -> None:
    log_embed = hikari.Embed(
        title="🖊️ Rolebutton Updated",
        description=f"**ID:** {event.rolebutton.id}\n**Channel:** <#{event.rolebutton.channel_id}>\n**Role:** <@&{event.rolebutton.role_id}>\n**Moderator:** `{display_user(event.moderator)}`",
        color=const.EMBED_BLUE,
    )
    await log(LogEvent.ROLES, log_embed, event.guild_id)


def load(bot: SnedBot) -> None:
    bot.add_plugin(userlog)
    userlog.d._task = bot.create_task(_iter_queue())


def unload(bot: SnedBot) -> None:
    if userlog.d._task:
        userlog.d._task.cancel()
    bot.remove_plugin(userlog)


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
