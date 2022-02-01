import asyncio
import datetime
import json
import logging
from typing import TypeVar, Union, Optional, Dict, Tuple

import hikari
import lightbulb

from models import SnedBot
from utils import helpers
from etc import perms_str

userlog = lightbulb.Plugin("Logging", include_datastore=True)

# Functions exposed to other extensions & plugins
userlog.d.actions = {}

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


async def log(
    log_event: str,
    log_content: Union[str, hikari.Embed],
    guild_id: int,
    file: Optional[hikari.File] = None,
    bypass: bool = False,
) -> None:
    """Log log_content into the channel assigned to log_event, if any."""

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

    file = file if file else hikari.UNDEFINED

    # Check if the channel still exists or not, and lazily invalidate it if not
    log_channel = userlog.app.cache.get_guild_channel(log_channel_id)
    if log_channel is None:
        return await set_log_channel(log_event, guild_id, None)

    try:
        await log_channel.send(content=content, embed=embed, file=file)
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
        return_next = False
        async for entry in userlog.app.rest.fetch_audit_log(guild, type=type):

            # We do not want to return entries older than 15 seconds
            if (helpers.utcnow() - entry.id.created_at).total_seconds() > 15 or return_next:
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


def get_perms_diff(old_role: hikari.Role, role: hikari.Role) -> str:
    """
    A helper function for displaying role updates.
    Returns a string containing the differences between two roles.
    """

    old_perms = old_role.permissions
    new_perms = role.permissions
    perm_diff = ""

    for perm in hikari.Permissions:
        if old_perms & perm and new_perms & perm:
            continue
        elif old_perms ^ perm and new_perms ^ perm:
            continue

        old_state = "Yes" if old_perms & perm else "No"
        new_state = "Yes" if new_perms & perm else "No"

        perms_diff = f"{perms_diff}\n   {perms_str[perm]}: {old_state} -> {new_state}"

    return perm_diff


T = TypeVar("T")


def get_diff(old_object: T, object: T, attrs: Dict[str, str]) -> str:
    """
    A helper function for displaying differences between certain attributes
    Returns a formatted string containing the differences.
    The two objects are expected to share the same attributes.
    """
    diff = ""
    for attribute in attrs.keys():
        if not hasattr(old_object, attribute):
            continue

        old = getattr(old_object, attribute)
        new = getattr(object, attribute)

        if hasattr(old, "name"):  # Handling flags enums
            diff = f"{diff}\n{attrs[attribute]}: {old.name} -> {new.name}" if old != new else diff
        elif isinstance(old, datetime.timedelta):  # Handling timedeltas
            diff = f"{diff}\n{attrs[attribute]}: {old.total_seconds()} -> {new.total_seconds()}" if old != new else diff
        else:
            diff = f"{diff}\n{attrs[attribute]}: {old} -> {new}" if old != new else diff


def create_log_content(message: hikari.Message, max_length: Optional[int] = None) -> str:
    """
    Process missing-content markers for messages before sending to logs
    """
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


def strip_bot_reason(reason: str) -> Tuple[str]:
    """
    Strip action author for it to be parsed into the actual embed instead of the bot
    """
    moderator = reason.split(" ")[0]  # Get actual moderator, not the bot
    reason = reason.split("): ", maxsplit=1)[1]  # Remove author
    return reason, moderator


# Event Listeners start below


@userlog.listener(hikari.GuildMessageDeleteEvent, bind=True)
async def message_delete(event: hikari.GuildMessageDeleteEvent, plugin: lightbulb.Plugin) -> None:
    if not event.old_message or event.old_message.author.is_bot:
        return

    contents = create_log_content(event.old_message)

    entry = await find_auditlog_data(
        event, type=hikari.AuditLogEventType.MESSAGE_DELETE, user_id=event.old_message.author.id
    )
    if entry:
        moderator: hikari.Member = plugin.app.cache.get_member(entry.user_id)
        embed = hikari.Embed(
            title=f"🗑️ Message deleted by Moderator",
            description=f"""**Message author:** `{event.old_message.author} ({event.old_message.author.id})`
**Moderator:** `{moderator} ({moderator.id})`
**Channel:** {event.old_message.channel.mention}
**Message content:** ```{contents}```""",
            color=plugin.app.error_color,
        )
        await log("message_delete_mod", embed, event.guild_id)

    else:
        embed = hikari.Embed(
            title=f"🗑️ Message deleted",
            description=f"""**Message author:** `{event.old_message.author} ({event.old_message.author.id})`
**Channel:** {event.old_message.channel.mention}
**Message content:** ```{contents}```""",
            color=plugin.app.error_color,
        )
        await log("message_delete", embed, event.guild_id)


@userlog.listener(hikari.GuildMessageUpdateEvent, bind=True)
async def message_update(event: hikari.GuildMessageUpdateEvent, plugin: lightbulb.Plugin) -> None:
    if not event.old_message or event.old_message.author.is_bot:
        return

    old_content = create_log_content(event.old_message, max_length=1800)
    new_content = create_log_content(event.message, max_length=1800)

    embed = hikari.Embed(
        title=f"🖊️ Message edited",
        description=f"""**Message author:** `{event.author} ({event.author.id})`
**Channel:** {event.get_channel().mention}
**Before:** ```{old_content}``` \n**After:** ```{new_content}```
[Jump!]({event.message.make_link(event.guild_id)})""",
        color=plugin.app.embed_blue,
    )
    await log("message_edit", embed, event.guild_id)


@userlog.listener(hikari.GuildBulkMessageDeleteEvent, bind=True)
async def bulk_message_delete(event: hikari.GuildBulkMessageDeleteEvent, plugin: lightbulb.Plugin) -> None:

    moderator = "Discord"
    entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.MESSAGE_BULK_DELETE)
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
async def role_delete(event: hikari.RoleDeleteEvent, plugin: lightbulb.Plugin) -> None:

    entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.ROLE_DELETE)
    if entry and event.old_role:
        moderator: hikari.Member = plugin.app.cache.get_member(entry.user_id)
        embed = hikari.Embed(
            title=f"🗑️ Role deleted",
            description=f"**Role:** `{event.old_role}`\n**Moderator:** `{moderator}`",
            color=plugin.app.error_color,
        )
        await log("roles", embed, event.guild_id)


@userlog.listener(hikari.RoleCreateEvent, bind=True)
async def role_create(event: hikari.RoleCreateEvent, plugin: lightbulb.Plugin) -> None:

    entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.ROLE_CREATE)
    if entry and event.role:
        moderator: hikari.Member = plugin.app.cache.get_member(entry.user_id)
        embed = hikari.Embed(
            title=f"❇️ Role created",
            description=f"**Role:** `{event.role}`\n**Moderator:** `{moderator}`",
            color=plugin.app.embed_green,
        )
        await log("roles", embed, event.guild_id)


@userlog.listener(hikari.RoleUpdateEvent, bind=True)
async def role_update(event: hikari.RoleUpdateEvent, plugin: lightbulb.Plugin) -> None:

    entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.ROLE_UPDATE)
    if entry and event.old_role:

        moderator: hikari.Member = plugin.app.cache.get_member(entry.user_id)

        attrs = {
            "position": "Position",
            "is_hoisted": "Hoisted",
            "is_mentionable": "Mentionable",
            "color": "Color",
            "icon_hash": "Icon Hash",
            "unicode_emoji": "Unicode Emoji",
        }
        diff = get_diff(event.old_role, event.role, attrs)
        perms_diff = get_perms_diff(event.old_role, event.new_role)

        embed = hikari.Embed(
            title=f"🖊️ Role updated",
            description=f"**Role:** `{event.role.name}` \n**Moderator:** `{moderator}```\n**Changes:**\n```{diff}\n'{f'Permissions:\n{perms_diff}'} if perms_diff != "
            " else "
            "}```",
            color=plugin.app.embed_blue,
        )
        await log("roles", embed, event.guild.id)


@userlog.listener(hikari.GuildChannelDeleteEvent, bind=True)
async def channel_delete(event: hikari.GuildChannelDeleteEvent, plugin: lightbulb.Plugin) -> None:

    entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.CHANNEL_DELETE)
    if entry and event.channel:
        moderator: hikari.Member = plugin.app.cache.get_member(entry.user_id)
        embed = hikari.Embed(
            title=f"#️⃣ Channel deleted",
            description=f"**Channel:** `{event.channel.name}` ({event.channel.type})\n**Moderator:** `{moderator} ({moderator})`",
            color=plugin.app.error_color,
        )
        await log("channels", embed, event.guild_id)


@userlog.listener(hikari.GuildChannelCreateEvent, bind=True)
async def channel_create(event: hikari.GuildChannelCreateEvent, plugin: lightbulb.Plugin) -> None:

    entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.CHANNEL_CREATE)
    if entry and event.channel:
        moderator: hikari.Member = plugin.app.cache.get_member(entry.user_id)
        embed = hikari.Embed(
            title=f"#️⃣ Channel created",
            description=f"**Channel:** {event.channel.mention} ({event.channel.type})\n**Moderator:** `{moderator} ({moderator})`",
            color=plugin.app.embed_green,
        )
        await log("channels", embed, event.guild_id)


@userlog.listener(hikari.GuildChannelUpdateEvent, bind=True)
async def channel_update(event: hikari.GuildChannelUpdateEvent, plugin: lightbulb.Plugin) -> None:

    entry = find_auditlog_data(event, type=hikari.AuditLogEventType.CHANNEL_UPDATE)

    if entry and event.old_channel:

        moderator: hikari.Member = plugin.app.cache.get_member(entry.user_id)

        attrs = {
            "name": "Name",
            "position": "Position",
            "permission_overwrites": "Permission Overwrites",
            "is_nsfw": "NSFW",
            "parent_id": "Category",
        }
        diff = get_diff(event.old_channel, event.channel, attrs)

        embed = hikari.Embed(
            title=f"#️⃣ Channel updated",
            description=f"Channel {event.channel.mention} was updated by `{moderator}`.\n**Changes:**\n```{diff}```",
            color=plugin.app.embed_blue,
        )
        await log("channels", embed, event.guild_id)


@userlog.listener(hikari.GuildUpdateEvent, bind=True)
async def guild_update(event: hikari.GuildUpdateEvent, plugin: lightbulb.Plugin) -> None:

    entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.GUILD_UPDATE)

    if event.old_guild:
        if entry:
            moderator: Union[hikari.Member, str] = plugin.app.cache.get_member(entry.user_id) if entry else "Discord"
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
            "is_large": "Is Large",
        }
        diff = get_diff(event.old_guild, event.guild, attrs)

        embed = hikari.Embed(
            title=f"🖊️ Guild updated",
            description=f"Guild settings have been updated by `{moderator}`.\n**Changes:**\n```{diff}```",
            color=plugin.app.embed_blue,
        )
        await log("guild_settings", embed, event.guild_id)


@userlog.listener(hikari.BanDeleteEvent, bind=True)
async def member_ban_remove(event: hikari.BanDeleteEvent, plugin: lightbulb.Plugin) -> None:

    entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.MEMBER_BAN_REMOVE, user_id=event.user.id)
    if entry:
        moderator: Union[hikari.Member, str] = plugin.app.cache.get_member(entry.user_id) if entry else "Unknown"
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
async def member_ban_add(event: hikari.BanCreateEvent, plugin: lightbulb.Plugin) -> None:

    entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.MEMBER_BAN_ADD, user_id=event.user.id)
    if entry:
        moderator: Union[hikari.Member, str] = plugin.app.cache.get_member(entry.user_id) if entry else "Unknown"
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
async def member_delete(event: hikari.MemberDeleteEvent, plugin: lightbulb.Plugin) -> None:

    entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.MEMBER_KICK, user_id=event.user.id)

    if entry:  # This is a kick
        moderator: Union[hikari.Member, str] = plugin.app.cache.get_member(entry.user_id) if entry else "Unknown"
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
async def member_create(event: hikari.MemberCreateEvent, plugin: lightbulb.Plugin) -> None:

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
async def member_update(event: hikari.MemberUpdateEvent, plugin: lightbulb.Plugin) -> None:

    if not event.old_member:
        return

    old_member = event.old_member
    member = event.member

    if old_member.communication_disabled_until != member.communication_disabled_until:
        """Timeout logging"""
        entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.MEMBER_UPDATE, user_id=event.user.id)

        if not entry:
            return

        if entry.reason == "Automatic timeout extension applied." and entry.user_id == plugin.app.get_me().id:
            return

        reason = entry.reason
        moderator: hikari.Member = plugin.app.cache.get_member(entry.user_id)

        if entry.user_id == plugin.app.get_me().id:
            reason, moderator = strip_bot_reason(reason)

        if member.communication_disabled_until is None:
            embed = helpers.Embed(
                title=f"🔉 User timeout removed",
                description=f"**User:** `{member.name} ({member.id})` \n**Moderator:** `{moderator}` \n**Reason:** ```{reason}```",
                color=plugin.app.embed_green,
            )
        else:
            embed = helpers.Embed(
                title=f"🔇 User timed out",
                description=f"""**User:** `{member.name} ({member.id})`
**Moderator:** `{moderator}` 
**Until:** {helpers.format_dt(member.communication_disabled_until)} ({helpers.format_dt(member.communication_disabled_until, style='R')})
**Reason:** ```{reason}```""",
                color=plugin.app.error_color,
            )
        await log("timeout", embed, event.guild_id)

    elif old_member.nickname != member.nickname:
        """Nickname change handling"""
        embed = hikari.Embed(
            title=f"🖊️ Nickname changed",
            description=f"**User:** `{member.name} ({member.id})`\nNickname before: `{old_member.nickname}`\nNickname after: `{member.nickname}`",
            color=plugin.app.embed_blue,
        )
        await log("nickname", embed, event.guild_id)

    elif old_member.role_ids != member.role_ids:
        # Check difference in roles between the two
        add_diff = list(set(member.role_ids) - set(old_member.role_ids))
        rem_diff = list(set(old_member.role_ids) - set(member.role_ids))

        entry = await find_auditlog_data(event, type=hikari.AuditLogEventType.MEMBER_ROLE_UPDATE, user_id=event.user.id)

        moderator: Union[hikari.Member, str] = plugin.app.cache.get_member(entry.user_id) if entry else "Unknown"
        reason: str = entry.reason

        if isinstance(moderator, (hikari.Member)) and moderator.is_bot:
            # Do not log role updates done by ourselves or other bots
            return

        if len(add_diff) != 0:
            role = plugin.app.cache.get_role(add_diff[0])
            embed = hikari.Embed(
                title=f"🖊️ Member roles updated",
                description=f"**User:** `{member} ({member.id})`\n**Moderator:** `{moderator}`\n**Role added:** `{role.mention}`",
                color=plugin.app.embed_blue,
            )
        elif len(rem_diff) != 0:
            role = plugin.app.cache.get_role(rem_diff[0])
            embed = hikari.Embed(
                title=f"🖊️ Member roles updated",
                description=f"**User:** `{member} ({member.id})`\n**Moderator:** `{moderator}`\n**Role removed:** `{role.mention}`",
                color=plugin.app.embed_blue,
            )

        await log("roles", embed, event.guild_id)


def load(bot: SnedBot) -> None:
    logging.info("Adding plugin: Logging")
    bot.add_plugin(userlog)


def unload(bot: SnedBot) -> None:
    logging.info("Removing plugin: Logging")
    bot.remove_plugin(userlog)
