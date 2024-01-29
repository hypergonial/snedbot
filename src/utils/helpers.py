from __future__ import annotations

import datetime
import re
import typing as t
import unicodedata
from contextlib import suppress

import hikari
import lightbulb
import pytz

from src.etc import const
from src.models import errors
from src.models.db_user import DatabaseUser

if t.TYPE_CHECKING:
    from src.models.client import SnedClient, SnedContext
    from src.models.journal import JournalEntry

MESSAGE_LINK_REGEX = re.compile(
    r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()!@:%_\+.~#?&\/\/=]*)channels[\/][0-9]{1,}[\/][0-9]{1,}[\/][0-9]{1,}"
)
LINK_REGEX = re.compile(
    r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()!@:%_\+.~#?&\/\/=]*)"
)
INVITE_REGEX = re.compile(r"(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?")

BADGE_EMOJI_MAPPING = {
    hikari.UserFlag.BUG_HUNTER_LEVEL_1: const.EMOJI_BUGHUNTER,
    hikari.UserFlag.BUG_HUNTER_LEVEL_2: const.EMOJI_BUGHUNTER_GOLD,
    hikari.UserFlag.DISCORD_CERTIFIED_MODERATOR: const.EMOJI_CERT_MOD,
    hikari.UserFlag.EARLY_SUPPORTER: const.EMOJI_EARLY_SUPPORTER,
    hikari.UserFlag.EARLY_VERIFIED_DEVELOPER: const.EMOJI_VERIFIED_DEVELOPER,
    hikari.UserFlag.HYPESQUAD_EVENTS: const.EMOJI_HYPESQUAD_EVENTS,
    hikari.UserFlag.HYPESQUAD_BALANCE: const.EMOJI_HYPESQUAD_BALANCE,
    hikari.UserFlag.HYPESQUAD_BRAVERY: const.EMOJI_HYPESQUAD_BRAVERY,
    hikari.UserFlag.HYPESQUAD_BRILLIANCE: const.EMOJI_HYPESQUAD_BRILLIANCE,
    hikari.UserFlag.PARTNERED_SERVER_OWNER: const.EMOJI_PARTNER,
    hikari.UserFlag.DISCORD_EMPLOYEE: const.EMOJI_STAFF,
}


def format_dt(time: datetime.datetime, style: str | None = None) -> str:
    """Convert a datetime into a Discord timestamp.

    For styling see this link: https://discord.com/developers/docs/reference#message-formatting-timestamp-styles.
    """
    valid_styles = ["t", "T", "d", "D", "f", "F", "R"]

    if style and style not in valid_styles:
        raise ValueError(f"Invalid style passed. Valid styles: {' '.join(valid_styles)}")

    if style:
        return f"<t:{int(time.timestamp())}:{style}>"

    return f"<t:{int(time.timestamp())}>"


def utcnow() -> datetime.datetime:
    """A short-hand function to return a timezone-aware utc datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


async def usernow(client: SnedClient, user: hikari.SnowflakeishOr[hikari.PartialUser]) -> datetime.datetime:
    """A short-hand function to return a datetime from the user's preferred timezone.

    Parameters
    ----------
    client : SnedClient
        The client instance.
    user : hikari.SnowflakeishOr[hikari.User]
        The user whose timezone preference to use.

    Returns
    -------
    datetime.datetime
        The current time in the user's timezone of preference.
    """
    records = await client.db_cache.get(table="preferences", user_id=hikari.Snowflake(user), limit=1)
    timezone = records[0].get("timezone") if records else "UTC"
    assert timezone is not None

    timezone = pytz.timezone(timezone)
    return datetime.datetime.now(timezone)


def add_embed_footer(embed: hikari.Embed, invoker: hikari.Member) -> hikari.Embed:
    """Add a note about the command invoker in the embed passed."""
    avatar_url = invoker.display_avatar_url

    embed.set_footer(text=f"Requested by {invoker}", icon=avatar_url)
    return embed


def get_color(member: hikari.Member) -> hikari.Color | None:
    roles = sort_roles(member.get_roles())
    if roles:
        for role in roles:
            if role.color != hikari.Color.from_rgb(0, 0, 0):
                return role.color

    return None


def sort_roles(roles: t.Sequence[hikari.Role]) -> t.Sequence[hikari.Role]:
    """Sort a list of roles in a descending order based on position."""
    return sorted(roles, key=lambda r: r.position, reverse=True)


def get_badges(user: hikari.User) -> t.Sequence[str]:
    """Return a list of badge emojies that the user has."""
    return [emoji for flag, emoji in BADGE_EMOJI_MAPPING.items() if flag & user.flags]


async def get_userinfo(ctx: SnedContext, user: hikari.User) -> hikari.Embed:
    if not ctx.guild_id:
        raise RuntimeError("Cannot use get_userinfo outside of a guild.")

    db_user = await DatabaseUser.fetch(user.id, ctx.guild_id)
    journal = await db_user.fetch_journal()

    member = ctx.client.cache.get_member(ctx.guild_id, user)

    if member:
        roles_list = [role.mention for role in sort_roles(member.get_roles()) if role.id != ctx.guild_id]
        roles = ", ".join(roles_list) if roles_list else "`-`"
        comms_disabled_until = member.communication_disabled_until()

        embed = hikari.Embed(
            title=f"**User information:** {member.display_name}",
            description=f"""**• Username:** `{member}`
**• Nickname:** `{member.nickname or "-"}`
**• User ID:** `{member.id}`
**• Bot:** `{member.is_bot}`
**• Account creation date:** {format_dt(member.created_at)} ({format_dt(member.created_at, style='R')})
**• Join date:** {format_dt(member.joined_at)} ({format_dt(member.joined_at, style='R')})
**• Badges:** {"   ".join(get_badges(member)) or "`-`"}
**• Warns:** `{db_user.warns}`
**• Timed out:** {f"Until: {format_dt(comms_disabled_until)}" if comms_disabled_until is not None else "`-`"}
**• Journal:** `{f"{len(journal)} entries" if journal else "No entries"}`
**• Roles:** {roles}""",
            color=get_color(member),
        )
        user = await ctx.client.rest.fetch_user(user.id)
        embed.set_thumbnail(member.display_avatar_url)
        if user.banner_url:
            embed.set_image(user.banner_url)

    else:
        embed = hikari.Embed(
            title=f"**User information:** {user.username}",
            description=f"""**• Username:** `{user}`
**• Nickname:** `-`
**• User ID:** `{user.id}`
**• Bot:** `{user.is_bot}`
**• Account creation date:** {format_dt(user.created_at)} ({format_dt(user.created_at, style='R')})
**• Join date:** `-`
**• Badges:** {"   ".join(get_badges(user)) or "`-`"}
**• Warns:** `{db_user.warns}`
**• Timed out:** `-`
**• Journal:** `{f"{len(journal)} entries" if journal else "No entries"}`
**• Roles:** `-`
*Note: This user is not a member of this server*""",
            color=const.EMBED_BLUE,
        )
        embed.set_thumbnail(user.display_avatar_url)
        user = await ctx.client.rest.fetch_user(user.id)
        if user.banner_url:
            embed.set_image(user.banner_url)

    assert ctx.member is not None

    if ctx.member.id in ctx.client.owner_ids:
        records = await ctx.client.db_cache.get(table="blacklist", guild_id=0, user_id=user.id, limit=1)
        is_blacklisted = bool(records) and records[0]["user_id"] == user.id
        embed.description = f"{embed.description}\n**• Blacklisted:** `{is_blacklisted}`"

    return embed


def includes_permissions(permissions: hikari.Permissions, should_include: hikari.Permissions) -> bool:
    """Check if permissions includes should_includes."""
    if permissions & hikari.Permissions.ADMINISTRATOR:
        return True

    missing_perms = ~permissions & should_include
    if missing_perms is not hikari.Permissions.NONE:
        return False
    return True


def normalize_string(string: str, strict: bool = False) -> str:
    """Normalize a unicode string and replace any similar characters from ones in the latin alphabet.

    Parameters
    ----------
    string : str
        The string to normalize.
    strict : bool
        Whether to use strict normalization. If True, may not preserve letters from other languages, such as cyrillic.

    Returns
    -------
    str
        The normalized string.
    """
    if strict:
        return unicodedata.normalize("NFKD", string.strip()).encode("ascii", "ignore").decode("ascii")
    return unicodedata.normalize("NFKC", string.strip())


def is_above(me: hikari.Member, member: hikari.Member) -> bool:
    """Returns True if me's top role's position is higher than the specified member's."""
    me_top_role = me.get_top_role()
    member_top_role = member.get_top_role()

    assert me_top_role is not None
    assert member_top_role is not None

    if me_top_role.position > member_top_role.position:
        return True
    return False


def can_harm(
    me: hikari.Member, member: hikari.Member, permission: hikari.Permissions, *, raise_error: bool = False
) -> bool:
    """Returns True if "member" can be harmed by "me", also checks if "me" has "permission"."""
    perms = lightbulb.utils.permissions_for(me)

    if not includes_permissions(perms, permission):
        if raise_error:
            raise lightbulb.BotMissingRequiredPermission(perms=permission)
        return False

    if not is_above(me, member):
        if raise_error:
            raise errors.RoleHierarchyError
        return False

    guild = member.get_guild()
    assert guild is not None

    if guild.owner_id == member.id:
        if raise_error:
            raise errors.RoleHierarchyError
        return False

    return True


def is_url(string: str, *, fullmatch: bool = True) -> bool:
    """Returns True if the provided string is an URL, otherwise False."""
    if fullmatch and LINK_REGEX.fullmatch(string) or not fullmatch and LINK_REGEX.match(string):
        return True

    return False


def is_invite(string: str, *, fullmatch: bool = True) -> bool:
    """Returns True if the provided string is a Discord invite, otherwise False."""
    if fullmatch and INVITE_REGEX.fullmatch(string) or not fullmatch and INVITE_REGEX.match(string):
        return True

    return False


def is_member(user: hikari.PartialUser) -> t.TypeGuard[hikari.Member]:
    """Determine if the passed object is a member or not, otherwise raise an error.
    Basically equivalent to `assert isinstance(user, hikari.Member)` but with a fancier error.
    """
    if isinstance(user, hikari.Member):
        return True

    raise errors.MemberExpectedError(f"Expected an instance of hikari.Member, not {user.__class__.__name__}!")


async def parse_message_link(ctx: SnedContext, message_link: str) -> hikari.Message | None:
    """Parse a message_link string into a message object.

    Parameters
    ----------
    ctx : SnedApplicationContext
        The context to parse the message link under.
    message_link : str
        The message link.

    Returns
    -------
    Optional[hikari.Message]
        The message object, if found.

    Raises
    ------
    lightbulb.BotMissingRequiredPermission
        The application is missing required permissions to acquire the message.
    """
    assert ctx.guild_id is not None

    if not MESSAGE_LINK_REGEX.fullmatch(message_link):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid link",
                description="This does not appear to be a valid message link! You can get a message's link by right-clicking it and selecting `Copy Message Link`!",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return None

    snowflakes = message_link.split("/channels/")[1].split("/")
    guild_id = hikari.Snowflake(snowflakes[0]) if snowflakes[0] != "@me" else None
    channel_id = hikari.Snowflake(snowflakes[1])
    message_id = hikari.Snowflake(snowflakes[2])

    if ctx.guild_id != guild_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid link",
                description="The message seems to be from another server! Please copy a message link from this server!",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return None

    channel = ctx.client.cache.get_guild_channel(channel_id)
    me = ctx.client.cache.get_member(ctx.guild_id, ctx.client.user_id)
    assert me is not None and isinstance(channel, hikari.TextableGuildChannel)

    if channel and isinstance(channel, hikari.PermissibleGuildChannel):  # Make reasonable attempt at checking perms
        perms = lightbulb.utils.permissions_in(channel, me)
        if not (perms & hikari.Permissions.READ_MESSAGE_HISTORY):
            raise lightbulb.BotMissingRequiredPermission(perms=hikari.Permissions.READ_MESSAGE_HISTORY)

    try:
        message = await ctx.client.rest.fetch_message(channel_id, message_id)
    except (hikari.NotFoundError, hikari.ForbiddenError):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Unknown message",
                description="Could not find message with this link. Ensure the link is valid, and that the bot has permissions to view the channel.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return None

    return message


async def maybe_delete(message: hikari.PartialMessage) -> None:
    with suppress(hikari.NotFoundError, hikari.ForbiddenError, hikari.HTTPError):
        await message.delete()


async def maybe_edit(message: hikari.PartialMessage, *args, **kwargs) -> None:
    with suppress(hikari.NotFoundError, hikari.ForbiddenError, hikari.HTTPError):
        await message.edit(*args, **kwargs)


def format_reason(
    reason: str | None = None, moderator: hikari.Member | None = None, *, max_length: int | None = 512
) -> str:
    """Format a reason for a moderation action.

    Parameters
    ----------
    reason : str | None, optional
        The reason for the action, by default None
    moderator : Optional[hikari.Member], optional
        The moderator who executed the action, by default None
    max_length : Optional[int], optional
        The maximum allowed length of the reason, by default 512

    Returns
    -------
    str
        The formatted reason
    """
    if not reason:
        reason = "No reason provided"

    if moderator:
        # This format must remain the same, as the userlog extension depends on it for author parsing.
        reason = f"{moderator} ({moderator.id}): {reason}"

    if max_length and len(reason) > max_length:
        reason = reason[: max_length - 3] + "..."

    return reason


def build_journal_pages(entries: list[JournalEntry]) -> list[hikari.Embed]:
    """Build a list of embeds to send to a user containing journal entries, with pagination."""
    paginator = lightbulb.utils.StringPaginator(max_chars=1500)
    for entry in entries:
        paginator.add_line(f"`#{entry.id}` {entry.display_content}")

    embeds = [
        hikari.Embed(
            title="📒 " + "Journal entries for this user:",
            description=page,
            color=const.EMBED_BLUE,
        )
        for page in paginator.build_pages()
    ]
    return embeds


# Copyright (C) 2022-present hypergonial

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
