import asyncio
import datetime
import json
import logging
from typing import TypeVar, Union, Optional, Dict, Tuple

import hikari
import lightbulb

from models import SnedBot
from utils import helpers
from etc import get_perm_str

userlog = lightbulb.Plugin("Logging", include_datastore=True)

# Functions exposed to other extensions & plugins
userlog.d.actions = lightbulb.utils.DataStore()

userlog.d.valid_log_events = [
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
userlog.d.frozen_guilds = []


async def get_log_channel_id(log_event: str, guild_id: int) -> Optional[int]:

    if log_event not in userlog.d.valid_log_events:
        raise ValueError("Invalid log_event passed.")

    records = await userlog.app.db_cache.get(table="log_config", guild_id=guild_id)

    log_channels = json.loads(records[0]["log_channels"]) if records and records[0]["log_channels"] else None

    return log_channels[log_event] if log_channels and log_event in log_channels.keys() else None


userlog.d.actions["get_log_channel_id"] = get_log_channel_id


async def get_log_channel_ids_view(guild_id: int) -> Dict[str, int]:
    """
    Return a mapping of log_event:channel_id
    """

    records = await userlog.app.db_cache.get(table="log_config", guild_id=guild_id)

    log_channels = json.loads(records[0]["log_channels"]) if records and records[0]["log_channels"] else {}

    for log_event in userlog.d.valid_log_events:
        if log_event not in log_channels.keys():
            log_channels[log_event] = None

    return log_channels


userlog.d.actions["get_log_channel_ids_view"] = get_log_channel_ids_view


async def set_log_channel(log_event: str, guild_id: int, channel_id: Optional[int] = None) -> None:
    """Sets logging channel for a given logging event."""

    if log_event not in userlog.d.valid_log_events:
        raise ValueError("Invalid log_event passed.")

    log_channels = await get_log_channel_ids_view(guild_id)
    log_channels[log_event] = channel_id
    await userlog.app.pool.execute(
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

    records = await userlog.app.db_cache.get(table="log_config", guild_id=guild_id)
    return records[0]["color"]


userlog.d.actions["is_color_enabled"] = is_color_enabled


async def log(
    log_event: str,
    log_content: Union[str, hikari.Embed],
    guild_id: int,
    file: hikari.UndefinedOr[hikari.File] = hikari.UNDEFINED,
    bypass: bool = False,
) -> None:
    """Log log_content into the channel assigned to log_event, if any.

    Parameters
    ----------
    log_event : str
        The channel associated with this event to post it under.
    log_content : Union[str, hikari.Embed]
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

    if isinstance(log_content, hikari.Embed):
        log_content.timestamp = datetime.datetime.now(datetime.timezone.utc)
        embed = log_content
        content = hikari.UNDEFINED

    elif isinstance(log_content, str):
        content = log_content
        embed = hikari.UNDEFINED

    # Check if the channel still exists or not, and lazily invalidate it if not
    log_channel = userlog.app.cache.get_guild_channel(log_channel_id)
    if log_channel is None:
        return await set_log_channel(log_event, guild_id, None)

    perms = lightbulb.utils.permissions_in(log_channel, userlog.app.cache.get_member(guild_id, userlog.app.user_id))
    if not (perms & hikari.Permissions.SEND_MESSAGES) or not (perms & hikari.Permissions.EMBED_LINKS):
        # Do not attempt message send if we have no perms
        return

    try:
        await log_channel.send(content=content, embed=embed, attachment=file)
    except (hikari.ForbiddenError, hikari.HTTPError):
        return


userlog.d.actions["log"] = log


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
    event: hikari.GuildEvent, *, event_type: hikari.AuditLogEventType, user_id: Optional[int] = hikari.UNDEFINED
) -> Optional[hikari.AuditLogEntry]:
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

    guild = userlog.app.cache.get_guild(event.guild_id)
    sleep_time = 5.0 if event_type not in takes_an_obscene_amount_of_time else 15.0
    await asyncio.sleep(sleep_time)  # Wait for auditlog to hopefully fill in

    if not guild:
        raise ValueError("Cannot find guild to parse auditlogs for.")

    perms = lightbulb.utils.permissions_for(userlog.app.cache.get_member(guild, userlog.app.user_id))
    if not (perms & hikari.Permissions.VIEW_AUDIT_LOG):
        # Do not attempt to fetch audit log if bot has no perms
        return

    try:
        return_next = False
        async for log in userlog.app.rest.fetch_audit_log(guild, event_type=event_type):
            for entry in log.entries.values():
                # We do not want to return entries older than 15 seconds
                if (helpers.utcnow() - entry.id.created_at).total_seconds() > 30 or return_next:
                    return

                if user_id and user_id == entry.target_id:
                    return entry
                elif user_id:
                    return_next = True  # Only do two calls at max
                    continue
                else:
                    return entry

    except hikari.ForbiddenError:
        return


async def get_perms_diff(old_role: hikari.Role, role: hikari.Role) -> str:
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

    return perms_diff.strip() + reset


T = TypeVar("T")


async def get_diff(guild_id: int, old_object: T, object: T, attrs: Dict[str, str]) -> str:
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
        old = getattr(old_object, attribute)
        new = getattr(object, attribute)

        if hasattr(old, "name"):  # Handling flags enums
            diff = (
                f"{diff}\n{white}{attrs[attribute]}: {red}{old.name} {gray}-> {green}{new.name}" if old != new else diff
            )
        elif isinstance(old, datetime.timedelta):  # Handling timedeltas
            diff = (
                f"{diff}\n{white}{attrs[attribute]}: {red}{old.total_seconds()} {gray}-> {green}{new.total_seconds()}"
                if old != new
                else diff
            )
        else:
            diff = f"{diff}\n{white}{attrs[attribute]}: {red}{old} {gray}-> {green}{new}" if old != new else diff
    return diff.strip() + reset


def create_log_content(message: hikari.Message, max_length: Optional[int] = None) -> str:
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


def strip_bot_reason(reason: str) -> Tuple[str]:
    """
    Strip action author for it to be parsed into the actual embed instead of the bot
    """
    moderator = reason.split(" ")[0]  # Get actual moderator, not the bot
    reason = reason.split("): ", maxsplit=1)[1]  # Remove author
    return reason, moderator


# Event Listeners start below


@userlog.listener(hikari.GuildMessageDeleteEvent, bind=True)
async def message_delete(plugin: lightbulb.Plugin, event: hikari.GuildMessageDeleteEvent) -> None:
    if not event.old_message or event.old_message.author.is_bot:
        return

    contents = create_log_content(event.old_message)

    entry = await find_auditlog_data(
        event, event_type=hikari.AuditLogEventType.MESSAGE_DELETE, user_id=event.old_message.author.id
    )
    if entry:
        moderator: hikari.Member = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title=f"🗑️ Message deleted by Moderator",
            description=f"""**Message author:** `{event.old_message.author} ({event.old_message.author.id})`
**Moderator:** `{moderator} ({moderator.id})`
**Channel:** {event.get_channel().mention}
**Message content:** ```{contents}```""",
            color=plugin.app.error_color,
        )
        await log("message_delete_mod", embed, event.guild_id)

    else:
        embed = hikari.Embed(
            title=f"🗑️ Message deleted",
            description=f"""**Message author:** `{event.old_message.author} ({event.old_message.author.id})`
**Channel:** {event.get_channel().mention}
**Message content:** ```{contents}```""",
            color=plugin.app.error_color,
        )
        await log("message_delete", embed, event.guild_id)


@userlog.listener(hikari.GuildMessageUpdateEvent, bind=True)
async def message_update(plugin: lightbulb.Plugin, event: hikari.GuildMessageUpdateEvent) -> None:
    if not event.old_message or event.old_message.author.is_bot or not event.author_id:
        return

    old_content = create_log_content(event.old_message, max_length=1800)
    new_content = create_log_content(event.message, max_length=1800)

    embed = hikari.Embed(
        title=f"🖊️ Message edited",
        description=f"""**Message author:** `{event.author} ({event.author_id})`
**Channel:** {event.get_channel().mention}
**Before:** ```{old_content}``` \n**After:** ```{new_content}```
[Jump!]({event.message.make_link(event.guild_id)})""",
        color=plugin.app.embed_blue,
    )
    await log("message_edit", embed, event.guild_id)


@userlog.listener(hikari.GuildBulkMessageDeleteEvent, bind=True)
async def bulk_message_delete(plugin: lightbulb.Plugin, event: hikari.GuildBulkMessageDeleteEvent) -> None:

    moderator = "Discord"
    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.MESSAGE_BULK_DELETE)
    if entry:
        moderator = plugin.app.cache.get_member(event.guild_id, entry.user_id)

    embed = hikari.Embed(
        title=f"🗑️ Bulk message deletion",
        description=f"""**Channel:** {event.get_channel().mention if event.get_channel() else 'Unknown'}
**Moderator:** `{moderator}`
```Multiple messages have been purged.```""",
        color=plugin.app.error_color,
    )
    await log("bulk_delete", embed, event.guild_id)


@userlog.listener(hikari.RoleDeleteEvent, bind=True)
async def role_delete(plugin: lightbulb.Plugin, event: hikari.RoleDeleteEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.ROLE_DELETE)
    if entry and event.old_role:
        moderator: hikari.Member = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title=f"🗑️ Role deleted",
            description=f"**Role:** `{event.old_role}`\n**Moderator:** `{moderator}`",
            color=plugin.app.error_color,
        )
        await log("roles", embed, event.guild_id)


@userlog.listener(hikari.RoleCreateEvent, bind=True)
async def role_create(plugin: lightbulb.Plugin, event: hikari.RoleCreateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.ROLE_CREATE)
    if entry and event.role:
        moderator: hikari.Member = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title=f"❇️ Role created",
            description=f"**Role:** `{event.role}`\n**Moderator:** `{moderator}`",
            color=plugin.app.embed_green,
        )
        await log("roles", embed, event.guild_id)


@userlog.listener(hikari.RoleUpdateEvent, bind=True)
async def role_update(plugin: lightbulb.Plugin, event: hikari.RoleUpdateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.ROLE_UPDATE)
    if entry and event.old_role:
        moderator: hikari.Member = plugin.app.cache.get_member(event.guild_id, entry.user_id)

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

        perms_str = f"\nPermissions: {perms_diff}" if perms_diff else ""
        embed = hikari.Embed(
            title=f"🖊️ Role updated",
            description=f"""**Role:** `{event.role.name}` \n**Moderator:** `{moderator}`\n**Changes:**```ansi\n{diff}{perms_str}```""",
            color=plugin.app.embed_blue,
        )
        await log("roles", embed, event.guild_id)


@userlog.listener(hikari.GuildChannelDeleteEvent, bind=True)
async def channel_delete(plugin: lightbulb.Plugin, event: hikari.GuildChannelDeleteEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.CHANNEL_DELETE)
    if entry and event.channel:
        moderator: hikari.Member = plugin.app.cache.get_member(entry.user_id)
        embed = hikari.Embed(
            title=f"#️⃣ Channel deleted",
            description=f"**Channel:** `{event.channel.name}` ({event.channel.type})\n**Moderator:** `{moderator} ({moderator})`",
            color=plugin.app.error_color,
        )
        await log("channels", embed, event.guild_id)


@userlog.listener(hikari.GuildChannelCreateEvent, bind=True)
async def channel_create(plugin: lightbulb.Plugin, event: hikari.GuildChannelCreateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.CHANNEL_CREATE)
    if entry and event.channel:
        moderator: hikari.Member = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        embed = hikari.Embed(
            title=f"#️⃣ Channel created",
            description=f"**Channel:** {event.channel.mention} ({event.channel.type})\n**Moderator:** `{moderator} ({moderator})`",
            color=plugin.app.embed_green,
        )
        await log("channels", embed, event.guild_id)


@userlog.listener(hikari.GuildChannelUpdateEvent, bind=True)
async def channel_update(plugin: lightbulb.Plugin, event: hikari.GuildChannelUpdateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.CHANNEL_UPDATE)

    if entry and event.old_channel:
        event.channel

        moderator: hikari.Member = plugin.app.cache.get_member(event.guild_id, entry.user_id)
        attrs = {
            "name": "Name",
            "position": "Position",
            "permission_overwrites": "Permission Overwrites",
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
        diff = diff or "Changes could not be resolved."

        embed = hikari.Embed(
            title=f"#️⃣ Channel updated",
            description=f"Channel {event.channel.mention} was updated by `{moderator}`.\n**Changes:**\n```ansi\n{diff}```",
            color=plugin.app.embed_blue,
        )
        await log("channels", embed, event.guild_id)


@userlog.listener(hikari.GuildUpdateEvent, bind=True)
async def guild_update(plugin: lightbulb.Plugin, event: hikari.GuildUpdateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.GUILD_UPDATE)

    if event.old_guild:
        if entry:
            moderator: Union[hikari.Member, str] = (
                plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry else "Discord"
            )
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
            color=plugin.app.embed_blue,
        )
        await log("guild_settings", embed, event.guild_id)


@userlog.listener(hikari.BanDeleteEvent, bind=True)
async def member_ban_remove(plugin: lightbulb.Plugin, event: hikari.BanDeleteEvent) -> None:

    entry = await find_auditlog_data(
        event, event_type=hikari.AuditLogEventType.MEMBER_BAN_REMOVE, user_id=event.user.id
    )
    if entry:
        moderator: Union[hikari.Member, str] = (
            plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry else "Unknown"
        )
        reason: Optional[str] = entry.reason or "No reason provided"
    else:
        moderator = "Error"
        reason = "Unable to view audit logs! Please ensure the bot has the necessary permissions to view them!"

    if moderator != "Unknown" and moderator.id == plugin.app.get_me().id:
        reason, moderator = strip_bot_reason(reason)

    embed = hikari.Embed(
        title=f"🔨 User unbanned",
        description=f"**Offender:** `{event.user} ({event.user.id})`\n**Moderator:**`{moderator}`\n**Reason:** ```{reason}```",
        color=plugin.app.embed_green,
    )
    await log("ban", embed, event.guild_id)


@userlog.listener(hikari.BanCreateEvent, bind=True)
async def member_ban_add(plugin: lightbulb.Plugin, event: hikari.BanCreateEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.MEMBER_BAN_ADD, user_id=event.user.id)
    if entry:
        moderator: Union[hikari.Member, str] = (
            plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry else "Unknown"
        )
        reason: Optional[str] = entry.reason or "No reason provided"
    else:
        moderator = "Unknown"
        reason = "Unable to view audit logs! Please ensure the bot has the necessary permissions to view them!"

    if moderator != "Unknown" and moderator.id == plugin.app.get_me().id:
        reason, moderator = strip_bot_reason(reason)

    embed = hikari.Embed(
        title=f"🔨 User banned",
        description=f"**Offender:** `{event.user} ({event.user.id})`\n**Moderator:**`{moderator}`\n**Reason:**```{reason}```",
        color=plugin.app.error_color,
    )
    await log("ban", embed, event.guild_id)


@userlog.listener(hikari.MemberDeleteEvent, bind=True)
async def member_delete(plugin: lightbulb.Plugin, event: hikari.MemberDeleteEvent) -> None:

    entry = await find_auditlog_data(event, event_type=hikari.AuditLogEventType.MEMBER_KICK, user_id=event.user.id)

    if entry:  # This is a kick
        moderator: Union[hikari.Member, str] = (
            plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry else "Unknown"
        )
        reason: Optional[str] = entry.reason or "No reason provided"

        if moderator != "Unknown" and moderator.id == plugin.app.get_me().id:
            reason, moderator = strip_bot_reason(reason)

        embed = hikari.Embed(
            title=f"🚪👈 User was kicked",
            description=f"**Offender:** `{event.user} ({event.user.id})`\n**Moderator:**`{moderator}`\n**Reason:**```{reason}```",
            color=plugin.app.error_color,
        )
        return await log("kick", embed, event.guild_id)

    embed = hikari.Embed(
        title=f"🚪 User left",
        description=f"**User:** `{event.user} ({event.user.id})`\n**User count:** `{len(plugin.app.cache.get_members_view_for_guild(event.guild_id))}`",
        color=plugin.app.error_color,
    )
    await log("member_leave", embed, event.guild_id)


@userlog.listener(hikari.MemberCreateEvent, bind=True)
async def member_create(plugin: lightbulb.Plugin, event: hikari.MemberCreateEvent) -> None:

    embed = hikari.Embed(
        title=f"🚪 User joined",
        description=f"**User:** `{event.member} ({event.member.id})`\n**User count:** `{len(plugin.app.cache.get_members_view_for_guild(event.guild_id))}`",
        color=plugin.app.embed_green,
    )
    embed.add_field(
        name="Account created",
        value=f"{helpers.format_dt(event.member.created_at)} ({helpers.format_dt(event.member.created_at, style='R')})",
        inline=False,
    )
    embed.set_thumbnail(helpers.get_display_avatar(event.member))
    await log("member_join", embed, event.guild_id)


@userlog.listener(hikari.MemberUpdateEvent, bind=True)
async def member_update(plugin: lightbulb.Plugin, event: hikari.MemberUpdateEvent) -> None:

    if not event.old_member:
        return

    old_member = event.old_member
    member = event.member

    if old_member.communication_disabled_until() != member.communication_disabled_until():
        """Timeout logging"""
        entry = await find_auditlog_data(
            event, event_type=hikari.AuditLogEventType.MEMBER_UPDATE, user_id=event.user.id
        )

        if not entry:
            return

        if entry.reason == "Automatic timeout extension applied." and entry.user_id == plugin.app.get_me().id:
            return

        reason = entry.reason
        moderator: hikari.Member = plugin.app.cache.get_member(event.guild_id, entry.user_id)

        if entry.user_id == plugin.app.get_me().id:
            reason, moderator = strip_bot_reason(reason)

        if member.communication_disabled_until() is None:
            embed = hikari.Embed(
                title=f"🔉 User timeout removed",
                description=f"**User:** `{member} ({member.id})` \n**Moderator:** `{moderator}` \n**Reason:** ```{reason}```",
                color=plugin.app.embed_green,
            )
        else:
            embed = hikari.Embed(
                title=f"🔇 User timed out",
                description=f"""**User:** `{member} ({member.id})`
**Moderator:** `{moderator}` 
**Until:** {helpers.format_dt(member.communication_disabled_until())} ({helpers.format_dt(member.communication_disabled_until(), style='R')})
**Reason:** ```{reason}```""",
                color=plugin.app.error_color,
            )
        await log("timeout", embed, event.guild_id)

    elif old_member.nickname != member.nickname:
        """Nickname change handling"""
        embed = hikari.Embed(
            title=f"🖊️ Nickname changed",
            description=f"**User:** `{member} ({member.id})`\nNickname before: `{old_member.nickname}`\nNickname after: `{member.nickname}`",
            color=plugin.app.embed_blue,
        )
        await log("nickname", embed, event.guild_id)

    elif old_member.role_ids != member.role_ids:
        # Check difference in roles between the two
        add_diff = list(set(member.role_ids) - set(old_member.role_ids))
        rem_diff = list(set(old_member.role_ids) - set(member.role_ids))

        if len(add_diff) == 0 and len(rem_diff) == 0:
            # No idea why this is needed, but otherwise I get empty role updates
            return

        entry = await find_auditlog_data(
            event, event_type=hikari.AuditLogEventType.MEMBER_ROLE_UPDATE, user_id=event.user.id
        )

        moderator: Union[hikari.Member, str] = (
            plugin.app.cache.get_member(event.guild_id, entry.user_id) if entry else "Unknown"
        )
        reason: str = entry.reason if entry else "No reason provided."

        if isinstance(moderator, (hikari.Member)) and moderator.is_bot:
            # Do not log role updates done by ourselves or other bots
            return

        if len(add_diff) != 0:
            role = plugin.app.cache.get_role(add_diff[0])
            embed = hikari.Embed(
                title=f"🖊️ Member roles updated",
                description=f"**User:** `{member} ({member.id})`\n**Moderator:** `{moderator}`\n**Role added:** {role.mention}",
                color=plugin.app.embed_blue,
            )
        elif len(rem_diff) != 0:
            role = plugin.app.cache.get_role(rem_diff[0])
            embed = hikari.Embed(
                title=f"🖊️ Member roles updated",
                description=f"**User:** `{member} ({member.id})`\n**Moderator:** `{moderator}`\n**Role removed:** {role.mention}",
                color=plugin.app.embed_blue,
            )

        await log("roles", embed, event.guild_id)


def load(bot: SnedBot) -> None:
    bot.add_plugin(userlog)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(userlog)
