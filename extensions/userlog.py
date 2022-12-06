import asyncio
import datetime
import json
import logging
import re
import sys
import traceback
import typing as t

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
from models.plugin import SnedPlugin
from utils import helpers

BOT_REASON_REGEX = re.compile(r"(?P<name>.*#\d{4})\s\((?P<id>\d+)\):\s(?P<reason>.*)")

logger = logging.getLogger(__name__)

userlog = SnedPlugin("Logging", include_datastore=True)

# Functions exposed to other extensions & plugins
userlog.d.actions = lightbulb.utils.DataStore()

# Mapping of channel_id: payload
userlog.d.queue = {}

# Queue iter task
userlog.d._task = None

userlog.d.valid_log_events = [
    "ban",
    "kick",
    "timeout",
    "message_delete",
    "message_delete_mod",
    "message_edit",
    "bulk_delete",
    "flags",
    "roles",
    "channels",
    "member_join",
    "member_leave",
    "nickname",
    "guild_settings",
    "warn",
]

# List of guilds where logging is temporarily suspended
userlog.d.frozen_guilds = []


async def get_log_channel_id(log_event: str, guild_id: int) -> t.Optional[int]:

    if log_event not in userlog.d.valid_log_events:
        raise ValueError("Invalid log_event passed.")

    records = await userlog.app.db_cache.get(table="log_config", guild_id=guild_id, limit=1)

    log_channels = json.loads(records[0]["log_channels"]) if records and records[0]["log_channels"] else None

    return log_channels.get(log_event) if log_channels else None


userlog.d.actions["get_log_channel_id"] = get_log_channel_id


async def get_log_channel_ids_view(guild_id: int) -> t.Dict[str, t.Optional[int]]:
    """
    Return a mapping of log_event:channel_id
    """

    records = await userlog.app.db_cache.get(table="log_config", guild_id=guild_id, limit=1)

    log_channels = json.loads(records[0]["log_channels"]) if records and records[0]["log_channels"] else {}

    for log_event in userlog.d.valid_log_events:
        if log_event not in log_channels.keys():
            log_channels[log_event] = None

    return log_channels


userlog.d.actions["get_log_channel_ids_view"] = get_log_channel_ids_view


async def set_log_channel(log_event: str, guild_id: int, channel_id: t.Optional[int] = None) -> None:
    """Sets logging channel for a given logging event."""

    if log_event not in userlog.d.valid_log_events:
        raise ValueError("Invalid log_event passed.")

    log_channels = await get_log_channel_ids_view(guild_id)
    log_channels[log_event] = channel_id
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
    log_event: str,
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

                embed_chunks: t.List[t.List[hikari.Embed]] = [[]]
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
    event: hikari.Event, *, event_type: hikari.AuditLogEventType, user_id: t.Optional[int] = None
) -> t.Optional[hikari.AuditLogEntry]:
    """Find a recently sent audit log entry that matches criteria.

    Parameters
    ----------
    event : hikari.GuildEvent
        The event that triggered this search.
    type : hikari.AuditLogEventType
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

    guild = userlog.app.cache.get_guild(event.guild_id)  # type: ignore
    sleep_time = 15.0 if event_type not in takes_an_obscene_amount_of_time else 30.0
    await asyncio.sleep(sleep_time)  # Wait for auditlog to hopefully fill in

    if not guild:
        raise ValueError("Cannot find guild to parse auditlogs for.")

    me = userlog.app.cache.get_member(guild, userlog.app.user_id)

    if me is None:
        return

    perms = lightbulb.utils.permissions_for(me)
    if not (perms & hikari.Permissions.VIEW_AUDIT_LOG):
        # Do not attempt to fetch audit log if bot has no perms
        return

    try:
        count = 0
        async for log in userlog.app.rest.fetch_audit_log(guild, event_type=event_type):
            for entry in log.entries.values():
                # We do not want to return entries older than 15 seconds
                if (helpers.utcnow() - entry.id.created_at).total_seconds() > 30 or count > 5:
                    return

                if user_id and user_id == entry.target_id:
                    return entry
                elif user_id:
                    count += 1
                    continue
                else:
                    return entry

    except (hikari.ForbiddenError, hikari.HTTPError, asyncio.TimeoutError):
        return


async def get_perms_diff(old_role: hikari.Role, role: hikari.Role) -> t.Optional[str]:
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


async def get_diff(guild_id: int, old_object: T, object: T, attrs: t.Dict[str, str]) -> t.Optional[str]:
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


def create_log_content(message: hikari.PartialMessage, max_length: t.Optional[int] = None) -> str:
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


def strip_bot_reason(reason: t.Optional[str]) -> t.Tuple[t.Optional[str], t.Optional[str]]:
    """
    Strip action author for it to be parsed into the actual embed instead of the bot
    """
    match = BOT_REASON_REGEX.match(str(reason))

    if not match:
        return reason, None

    return match.group("reason"), match.group("name")


# Event Listeners start below


@userlog.listener(hikari.GuildMessageDeleteEvent, bind=True)
async def message_delete(plugin: SnedPlugin, event: hikari.GuildMessageDeleteEvent) -> None:
    if not event.old_message or event.old_message.author.is_bot:
        return

    contents = create_log_content(event.old_message)

    entry = await find_auditlog_data(
        event, event_type=hikari.AuditLogEventType.MESSAGE_DELETE, user_id=event.old_message.author.id
    )

    if entry:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        assert moderator is not None

        embed = hikari.Embed(
            title=f"🗑️ Message deleted by Moderator",
            description=f"""**Message author:** `{event.old_message.author} ({event.old_message.author.id})`
**Moderator:** `{moderator} ({moderator.id})`
**Channel:** <#{event.channel_id}>
**Message content:** ```{contents}```""",
            color=const.ERROR_COLOR,
        )
        await log("message_delete_mod", embed, event.guild_id)

    else:
        embed = hikari.Embed(
            title=f"🗑️ Message deleted",
            description=f"""**Message author:** `{event.old_message.author} ({event.old_message.author.id})`
**Channel:** <#{event.channel_id}>
**Message content:** ```{contents}```""",
            color=const.ERROR_COLOR,
        )
        await log("message_delete", embed, event.guild_id)


@userlog.listener(hikari.GuildMessageUpdateEvent, bind=True)
async def message_update(plugin: SnedPlugin, event: hikari.GuildMessageUpdateEvent) -> None:
    if not event.old_message or not event.old_message.author or event.old_message.author.is_bot:
        return

    if (event.old_message.flags and not hikari.MessageFlag.CROSSPOSTED & event.old_message.flags) and (
        event.message.flags and hikari.MessageFlag.CROSSPOSTED & event.message.flags
    ):
        return

    assert event.old_message and event.message

    old_content = create_log_content(event.old_message, max_length=1800)
    new_content = create_log_content(event.message, max_length=1800)

    embed = hikari.Embed(
        title=f"🖊️ Message edited",
        description=f"""**Message author:** `{event.author} ({event.author_id})`
**Channel:** <#{event.channel_id}>
**Before:** ```{old_content}``` \n**After:** ```{new_content}```
[Jump!]({event.message.make_link(event.guild_id)})""",
        color=const.EMBED_BLUE,
    )
    await log("message_edit", embed, event.guild_id)


@userlog.listener(hikari.GuildBulkMessageDeleteEvent, bind=True)
async def bulk_message_delete(plugin: SnedPlugin, event: hikari.GuildBulkMessageDeleteEvent) -> None:

    moderator = "Discord"
    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.MESSAGE_BULK_DELETE)
    if entry:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)

    channel = event.get_channel()

    embed = hikari.Embed(
        title=f"🗑️ Bulk message deletion",
        description=f"""**Channel:** {channel.mention if channel else 'Unknown'}
**Moderator:** `{moderator}`
```Multiple messages have been purged.```""",
        color=const.ERROR_COLOR,
    )
    await log("bulk_delete", embed, event.guild_id)


@userlog.listener(hikari.RoleDeleteEvent, bind=True)
async def role_delete(plugin: SnedPlugin, event: hikari.RoleDeleteEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.ROLE_DELETE)
    if entry and event.old_role:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title=f"🗑️ Role deleted",
            description=f"**Role:** `{event.old_role}`\n**Moderator:** `{moderator}`",
            color=const.ERROR_COLOR,
        )
        await log("roles", embed, event.guild_id)


@userlog.listener(hikari.RoleCreateEvent, bind=True)
async def role_create(plugin: SnedPlugin, event: hikari.RoleCreateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.ROLE_CREATE)
    if entry and event.role:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title=f"❇️ Role created",
            description=f"**Role:** `{event.role}`\n**Moderator:** `{moderator}`",
            color=const.EMBED_GREEN,
        )
        await log("roles", embed, event.guild_id)


@userlog.listener(hikari.RoleUpdateEvent, bind=True)
async def role_update(plugin: SnedPlugin, event: hikari.RoleUpdateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.ROLE_UPDATE)
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
            title=f"🖊️ Role updated",
            description=f"""**Role:** `{event.role.name}` \n**Moderator:** `{moderator}`\n**Changes:**```ansi\n{diff}{perms_str}```""",
            color=const.EMBED_BLUE,
        )
        await log("roles", embed, event.guild_id)


@userlog.listener(hikari.GuildChannelDeleteEvent, bind=True)
async def channel_delete(plugin: SnedPlugin, event: hikari.GuildChannelDeleteEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.CHANNEL_DELETE)
    if entry and event.channel:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title=f"#️⃣ Channel deleted",
            description=f"**Channel:** `{event.channel.name}` `({event.channel.type.name})`\n**Moderator:** `{moderator}` {f'`({moderator.id})`' if moderator else ''}",  # type: ignore
            color=const.ERROR_COLOR,
        )
        await log("channels", embed, event.guild_id)


@userlog.listener(hikari.GuildChannelCreateEvent, bind=True)
async def channel_create(plugin: SnedPlugin, event: hikari.GuildChannelCreateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.CHANNEL_CREATE)
    if entry and event.channel:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title=f"#️⃣ Channel created",
            description=f"**Channel:** {event.channel.mention} `({event.channel.type.name})`\n**Moderator:** `{moderator}` {f'`({moderator.id})`' if moderator else ''}",  # type: ignore
            color=const.EMBED_GREEN,
        )
        await log("channels", embed, event.guild_id)


@userlog.listener(hikari.GuildChannelUpdateEvent, bind=True)
async def channel_update(plugin: SnedPlugin, event: hikari.GuildChannelUpdateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.CHANNEL_UPDATE)

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
            title=f"#️⃣ Channel updated",
            description=f"Channel {event.channel.mention} was updated by `{moderator}` {f'`({moderator.id})`' if moderator else ''}.\n**Changes:**\n```ansi\n{diff}```",
            color=const.EMBED_BLUE,
        )
        await log("channels", embed, event.guild_id)


@userlog.listener(hikari.GuildUpdateEvent, bind=True)
async def guild_update(plugin: SnedPlugin, event: hikari.GuildUpdateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.GUILD_UPDATE)

    if event.old_guild:
        if entry:
            assert entry.user_id is not None
            moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry else "Discord"
            moderator = moderator or "Discord"
        else:
            moderator = "Discord"

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
            title=f"🖊️ Guild updated",
            description=f"Guild settings have been updated by `{moderator}`.\n**Changes:**\n```ansi\n{diff}```",
            color=const.EMBED_BLUE,
        )
        await log("guild_settings", embed, event.guild_id)


@userlog.listener(hikari.BanDeleteEvent, bind=True)
async def member_ban_remove(plugin: SnedPlugin, event: hikari.BanDeleteEvent) -> None:

    entry = await find_auditlog_data(
        event, event_type=hikari.AuditLogEventType.MEMBER_BAN_REMOVE, user_id=event.user.id
    )
    if entry:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry else "Unknown"
        reason: t.Optional[str] = entry.reason or "No reason provided"
    else:
        moderator = "Error"
        reason = "Unable to view audit logs! Please ensure the bot has the necessary permissions to view them!"

    if isinstance(moderator, hikari.Member) and moderator.id == plugin.app.user_id:
        reason, moderator = strip_bot_reason(reason)
        moderator = moderator or plugin.app.get_me()

    embed = hikari.Embed(
        title=f"🔨 User unbanned",
        description=f"**Offender:** `{event.user} ({event.user.id})`\n**Moderator:**`{moderator}`\n**Reason:** ```{reason}```",
        color=const.EMBED_GREEN,
    )
    await log("ban", embed, event.guild_id)
    await plugin.app.mod.add_note(event.user, event.guild_id, f"🔨 **Unbanned by {moderator}:** {reason}")


@userlog.listener(hikari.BanCreateEvent, bind=True)
async def member_ban_add(plugin: SnedPlugin, event: hikari.BanCreateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.MEMBER_BAN_ADD, user_id=event.user.id)
    if entry:
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry else "Unknown"
        reason: t.Optional[str] = entry.reason or "No reason provided"
    else:
        moderator = "Unknown"
        reason = "Unable to view audit logs! Please ensure the bot has the necessary permissions to view them!"

    if isinstance(moderator, hikari.Member) and moderator.id == plugin.app.user_id:
        reason, moderator = strip_bot_reason(reason)
        moderator = moderator or plugin.app.get_me()

    embed = hikari.Embed(
        title=f"🔨 User banned",
        description=f"**Offender:** `{event.user} ({event.user.id})`\n**Moderator:**`{moderator}`\n**Reason:**```{reason}```",
        color=const.ERROR_COLOR,
    )
    await log("ban", embed, event.guild_id)
    await plugin.app.mod.add_note(event.user, event.guild_id, f"🔨 **Banned by {moderator}:** {reason}")


@userlog.listener(hikari.MemberDeleteEvent, bind=True)
async def member_delete(plugin: SnedPlugin, event: hikari.MemberDeleteEvent) -> None:

    if event.user_id == plugin.app.user_id:
        return  # RIP

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.MEMBER_KICK, user_id=event.user.id)

    if entry:  # This is a kick
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry else "Unknown"
        reason: t.Optional[str] = entry.reason or "No reason provided"

        if isinstance(moderator, hikari.Member) and moderator.id == plugin.app.user_id:
            reason, moderator = strip_bot_reason(reason)
            moderator = moderator or plugin.app.get_me()

        embed = hikari.Embed(
            title=f"🚪👈 User was kicked",
            description=f"**Offender:** `{event.user} ({event.user.id})`\n**Moderator:**`{moderator}`\n**Reason:**```{reason}```",
            color=const.ERROR_COLOR,
        )
        await log("kick", embed, event.guild_id)
        await plugin.app.mod.add_note(event.user, event.guild_id, f"🚪👈 **Kicked by {moderator}:** {reason}")
        return

    embed = hikari.Embed(
        title=f"🚪 User left",
        description=f"**User:** `{event.user} ({event.user.id})`\n**User count:** `{len(plugin.app.cache.get_members_view_for_guild(event.guild_id))}`",
        color=const.ERROR_COLOR,
    )
    await log("member_leave", embed, event.guild_id)


@userlog.listener(hikari.MemberCreateEvent, bind=True)
async def member_create(plugin: SnedPlugin, event: hikari.MemberCreateEvent) -> None:

    embed = hikari.Embed(
        title=f"🚪 User joined",
        description=f"**User:** `{event.member} ({event.member.id})`\n**User count:** `{len(plugin.app.cache.get_members_view_for_guild(event.guild_id))}`",
        color=const.EMBED_GREEN,
    )
    embed.add_field(
        name="Account created",
        value=f"{helpers.format_dt(event.member.created_at)} ({helpers.format_dt(event.member.created_at, style='R')})",
        inline=False,
    )
    embed.set_thumbnail(event.member.display_avatar_url)
    await log("member_join", embed, event.guild_id)


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
            event, event_type=hikari.AuditLogEventType.MEMBER_UPDATE, user_id=event.user.id
        )
        if not entry:
            return

        if entry.reason == "Automatic timeout extension applied." and entry.user_id == plugin.app.user_id:
            return

        reason = entry.reason
        assert entry.user_id is not None
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)

        if entry.user_id == plugin.app.user_id:
            reason, moderator = strip_bot_reason(reason)
            moderator = moderator or str(plugin.app.get_me())

        if comms_disabled_until is None:
            embed = hikari.Embed(
                title=f"🔉 User timeout removed",
                description=f"**User:** `{member} ({member.id})` \n**Moderator:** `{moderator}` \n**Reason:** ```{reason}```",
                color=const.EMBED_GREEN,
            )
            await plugin.app.mod.add_note(event.user, event.guild_id, f"🔉 **Timeout removed by {moderator}:** {reason}")

        else:
            assert comms_disabled_until is not None

            embed = hikari.Embed(
                title=f"🔇 User timed out",
                description=f"""**User:** `{member} ({member.id})`
**Moderator:** `{moderator}` 
**Until:** {helpers.format_dt(comms_disabled_until)} ({helpers.format_dt(comms_disabled_until, style='R')})
**Reason:** ```{reason}```""",
                color=const.ERROR_COLOR,
            )
            await plugin.app.mod.add_note(
                event.user,
                event.guild_id,
                f"🔇 **Timed out by {moderator} until {helpers.format_dt(comms_disabled_until)}:** {reason}",
            )

        await log("timeout", embed, event.guild_id)

    elif old_member.nickname != member.nickname:
        """Nickname change handling"""
        embed = hikari.Embed(
            title=f"🖊️ Nickname changed",
            description=f"**User:** `{member} ({member.id})`\nNickname before: `{old_member.nickname}`\nNickname after: `{member.nickname}`",
            color=const.EMBED_BLUE,
        )
        await log("nickname", embed, event.guild_id)

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
            event, event_type=hikari.AuditLogEventType.MEMBER_ROLE_UPDATE, user_id=event.user.id
        )

        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry and entry.user_id else "Unknown"

        if entry and entry.user_id == plugin.app.user_id:
            # Attempt to find the moderator in reason if sent by us
            _, moderator = strip_bot_reason(entry.reason)
            moderator = moderator or plugin.app.get_me()

        if isinstance(moderator, (hikari.User)) and moderator.is_bot:
            # Do not log role updates done by ourselves or other bots
            # Provided that the role was not added through /role
            return

        if add_diff:
            embed = hikari.Embed(
                title=f"🖊️ Member roles updated",
                description=f"**User:** `{member} ({member.id})`\n**Moderator:** `{moderator}`\n**Role added:** <@&{add_diff[0]}>",
                color=const.EMBED_BLUE,
            )
            await log("roles", embed, event.guild_id)

        elif rem_diff:
            embed = hikari.Embed(
                title=f"🖊️ Member roles updated",
                description=f"**User:** `{member} ({member.id})`\n**Moderator:** `{moderator}`\n**Role removed:** <@&{rem_diff[0]}>",
                color=const.EMBED_BLUE,
            )
            await log("roles", embed, event.guild_id)


@userlog.listener(WarnCreateEvent, bind=True)
async def warn_create(plugin: SnedPlugin, event: WarnCreateEvent) -> None:

    embed = hikari.Embed(
        title="⚠️ Warning issued",
        description=f"**{event.member}** has been warned by **{event.moderator}**.\n**Warns:** {event.warn_count}\n**Reason:** ```{event.reason}```",
        color=const.WARN_COLOR,
    )

    await log("warn", embed, event.guild_id)

    await plugin.app.mod.add_note(
        event.member, event.member.guild_id, f"⚠️ **Warned by {event.moderator}:** {event.reason}"
    )


@userlog.listener(WarnRemoveEvent, bind=True)
async def warn_remove(plugin: SnedPlugin, event: WarnRemoveEvent) -> None:

    embed = hikari.Embed(
        title="⚠️ Warning removed",
        description=f"A warning was removed from **{event.member}** by **{event.moderator}**.\n**Warns:** {event.warn_count}\n**Reason:** ```{event.reason}```",
        color=const.EMBED_GREEN,
    )

    await log("warn", embed, event.guild_id)

    await plugin.app.mod.add_note(
        event.member, event.member.guild_id, f"⚠️ **1 Warning removed by {event.moderator}:** {event.reason}"
    )


@userlog.listener(WarnsClearEvent, bind=True)
async def warns_clear(plugin: SnedPlugin, event: WarnsClearEvent) -> None:

    embed = hikari.Embed(
        title="⚠️ Warnings cleared",
        description=f"Warnings cleared for **{event.member}** by **{event.moderator}**.\n**Reason:** ```{event.reason}```",
        color=const.EMBED_GREEN,
    )

    await log("warn", embed, event.guild_id)

    await plugin.app.mod.add_note(
        event.member, event.member.guild_id, f"⚠️ **Warnings cleared for {event.moderator}:** {event.reason}"
    )


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
        description=f"**{user}** `({user.id})` was flagged by auto-moderator for suspicious behaviour.\n**Reason:**```{reason}```\n**Content:** ```{content}```\n\n[Jump to message!]({event.message.make_link(event.guild_id)})",
        color=const.ERROR_COLOR,
    )
    await log("flags", embed, event.guild_id)


@userlog.listener(MassBanEvent)
async def massban_execute(event: MassBanEvent) -> None:

    log_embed = hikari.Embed(
        title="🔨 Smartban concluded",
        description=f"Banned **{event.successful}/{event.total}** users.\n**Moderator:** `{event.moderator} ({event.moderator.id})`\n**Reason:** ```{event.reason}```",
        color=const.ERROR_COLOR,
    )
    await log("ban", log_embed, event.guild_id, file=event.users_file, bypass=True)


@userlog.listener(RoleButtonCreateEvent)
async def rolebutton_create(event: RoleButtonCreateEvent) -> None:
    moderator = f"{event.moderator} ({event.moderator.id})" if event.moderator else "Unknown"

    log_embed = hikari.Embed(
        title="❇️ Rolebutton Added",
        description=f"**ID:** {event.rolebutton.id}\n**Channel:** <#{event.rolebutton.channel_id}>\n**Role:** <@&{event.rolebutton.role_id}>\n**Moderator:** `{moderator}`",
        color=const.EMBED_GREEN,
    )
    await log("roles", log_embed, event.guild_id)


@userlog.listener(RoleButtonDeleteEvent)
async def rolebutton_delete(event: RoleButtonDeleteEvent) -> None:
    moderator = f"{event.moderator} ({event.moderator.id})" if event.moderator else "Unknown"

    log_embed = hikari.Embed(
        title="🗑️ Rolebutton Deleted",
        description=f"**ID:** {event.rolebutton.id}\n**Channel:** <#{event.rolebutton.channel_id}>\n**Role:** <@&{event.rolebutton.role_id}>\n**Moderator:** `{moderator}`",
        color=const.ERROR_COLOR,
    )
    await log("roles", log_embed, event.guild_id)


@userlog.listener(RoleButtonUpdateEvent)
async def rolebutton_update(event: RoleButtonUpdateEvent) -> None:
    moderator = f"{event.moderator} ({event.moderator.id})" if event.moderator else "Unknown"

    log_embed = hikari.Embed(
        title="🖊️ Rolebutton Updated",
        description=f"**ID:** {event.rolebutton.id}\n**Channel:** <#{event.rolebutton.channel_id}>\n**Role:** <@&{event.rolebutton.role_id}>\n**Moderator:** `{moderator}`",
        color=const.EMBED_BLUE,
    )
    await log("roles", log_embed, event.guild_id)


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
