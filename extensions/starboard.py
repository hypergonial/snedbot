import logging
import re
import typing as t

import hikari
import lightbulb

from etc import const
from models.bot import SnedBot
from models.context import SnedSlashContext
from models.plugin import SnedPlugin
from utils import helpers

# Mapping of message_id: starboard_message_id
starboard_messages = {}

logger = logging.getLogger(__name__)

starboard = SnedPlugin("Starboard")

IMAGE_URL_REGEX = re.compile(
    r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()!@:%_\+.~#?&\/\/=]*)([.]jpe?g|png|gif|bmp|webp)[-a-zA-Z0-9@:%._\+~#=?&]*"
)

STAR_MAPPING = {
    "⭐": 0,
    "🌟": 5,
    "✨": 10,
    "💫": 15,
}


def get_image_url(content: str) -> t.Optional[str]:
    """Return a list of image URLs found in the message content."""

    matches: t.Optional[re.Match[str]] = re.search(IMAGE_URL_REGEX, content)

    if not matches:
        return None

    return content[matches.span()[0] : matches.span()[1]]


def get_attachment_url(message: hikari.Message) -> t.Optional[str]:
    """Return a list of image attachment URLs found in the message."""

    if not message.attachments:
        return

    attach_urls = [attachment.url for attachment in message.attachments]
    string = " ".join(attach_urls)

    matches: t.Optional[re.Match[str]] = re.search(IMAGE_URL_REGEX, string)

    if not matches:
        return None

    return string[matches.span()[0] : matches.span()[1]]


def create_starboard_payload(
    guild: hikari.SnowflakeishOr[hikari.PartialGuild], message: hikari.Message, stars: int
) -> t.Dict[str, t.Any]:
    """Create message payload for a starboard entry.

    Parameters
    ----------
    guild : hikari.SnowflakeishOr[hikari.PartialGuild]
        The guild the starboard entry is located.
    message : hikari.Message
        The message to create the payload from.
    stars : int
        The amount of stars the message has.

    Returns
    -------
    t.Dict[str, t.Any]
        The payload as keyword arguments.
    """

    guild_id = hikari.Snowflake(guild)
    emoji = [emoji for emoji, value in STAR_MAPPING.items() if value <= stars][-1]
    content = f"{emoji} **{stars}** <#{message.channel_id}>"
    embed = (
        hikari.Embed(description=message.content, color=0xFFC20C)
        .set_author(name=str(message.author), icon=message.author.display_avatar_url)
        .set_footer(f"ID: {message.id}")
    )
    attachments = message.attachments

    if image_urls := get_attachment_url(message):
        embed.set_image(image_urls)
        attachments = [attachment for attachment in attachments if attachment.url != image_urls]

    elif message.content:
        if image_urls := get_image_url(message.content):
            embed.set_image(image_urls)

    if attachments:
        embed.add_field(
            "Attachments", "\n".join([f"[{attachment.filename[:100]}]({attachment.url})" for attachment in attachments])
        )

    if message.referenced_message:
        embed.add_field(
            "Replying to",
            f"[{message.referenced_message.author}]({message.referenced_message.make_link(guild_id)})",
        )

    embed.add_field("Original Message", f"[Jump!]({message.make_link(guild_id)})")

    return {"content": content, "embed": embed}


async def star_message(
    message: hikari.Message,
    guild: hikari.SnowflakeishOr[hikari.PartialGuild],
    starboard_channel: hikari.SnowflakeishOr[hikari.TextableGuildChannel],
    stars: int,
) -> None:
    """Create or edit an existing star entry on the starboard.

    Parameters
    ----------
    message : hikari.Message
        The message to be starred.
    starboard_channel : hikari.SnowflakeishOr[hikari.TextableGuildChannel]
        The channel where the message should be starred.
    guild : hikari.SnowflakeishOr[hikari.PartialGuild]
        The guild the message and channel are located.
    stars : int
        The amount of stars the message is supposed to have when posted.
    """

    star_channel_id = hikari.Snowflake(starboard_channel)

    starboard_msg_id = starboard_messages.get(message.id)
    payload = create_starboard_payload(guild, message, stars)

    if not starboard_msg_id:
        record = await starboard.app.db.fetchrow(
            f"""SELECT entry_msg_id FROM starboard_entries WHERE orig_msg_id = $1""", message.id
        )

        if not record:
            # Create new entry
            starboard_msg_id = (await starboard.app.rest.create_message(star_channel_id, **payload)).id
            starboard_messages[message.id] = starboard_msg_id

            await starboard.app.db.execute(
                """INSERT INTO starboard_entries 
                (guild_id, channel_id, orig_msg_id, entry_msg_id) 
                VALUES ($1, $2, $3, $4) ON CONFLICT (guild_id, channel_id, orig_msg_id) DO NOTHING""",
                hikari.Snowflake(guild),
                message.channel_id,
                message.id,
                starboard_msg_id,
            )
            return

        else:
            starboard_msg_id = record["entry_msg_id"]
            starboard_messages[message.id] = starboard_msg_id

    try:
        await starboard.app.rest.edit_message(star_channel_id, starboard_msg_id, **payload)
    except hikari.NotFoundError:
        # Delete entry, re-run logic to create a new starboard entry
        await starboard.app.db.execute(f"""DELETE FROM starboard_entries WHERE entry_msg_id = $1""", starboard_msg_id)
        starboard_messages.pop(message.id, None)
        await star_message(message, guild, starboard_channel, stars)


@starboard.listener(hikari.GuildReactionDeleteEvent, bind=True)
@starboard.listener(hikari.GuildReactionAddEvent, bind=True)
async def on_reaction(
    plugin: SnedPlugin, event: t.Union[hikari.GuildReactionAddEvent, hikari.GuildReactionDeleteEvent]
) -> None:
    """Listen for reactions & star messages where appropriate."""

    if not event.is_for_emoji("⭐") or not plugin.app.is_started:
        return

    records = await plugin.app.db_cache.get(table="starboard", guild_id=event.guild_id, limit=1)

    if not records:
        return

    settings = records[0]

    if not settings["channel_id"] or not settings["is_enabled"]:
        return

    if settings["channel_id"] == event.channel_id:
        # Ignore stars in the starboard channel to prevent starring of star entries
        return

    me = plugin.app.cache.get_member(event.guild_id, plugin.app.user_id)

    if not me:
        return

    if channel := plugin.app.cache.get_guild_channel(settings["channel_id"]):

        perms = lightbulb.utils.permissions_in(channel, me)
        if not helpers.includes_permissions(
            perms,
            hikari.Permissions.SEND_MESSAGES
            | hikari.Permissions.VIEW_CHANNEL
            | hikari.Permissions.READ_MESSAGE_HISTORY,
        ):
            return

    else:
        # We store a channel_id but the channel was deleted, so we get rid of all data
        async with plugin.app.db.acquire() as con:
            await con.execute("""UPDATE starboard SET channel_id = null WHERE guild_id = $1""", event.guild_id)
            await con.execute("""DELETE FROM starboard_entries WHERE guild_id = $1""", event.guild_id)
        await plugin.app.db_cache.refresh(table="starboard", guild_id=event.guild_id)
        return

    if event.channel_id in settings["excluded_channels"]:
        return

    # Check perms if channel is cached
    if channel := plugin.app.cache.get_guild_channel(event.channel_id):
        perms = lightbulb.utils.permissions_in(channel, me)
        if not helpers.includes_permissions(
            perms,
            hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY,
        ):
            return

    message = await plugin.app.rest.fetch_message(event.channel_id, event.message_id)
    reactions = [reaction for reaction in message.reactions if str(reaction.emoji) == "⭐"]

    stars = reactions[0].count if reactions else 0

    if stars < settings["star_limit"]:
        return

    await star_message(message, event.guild_id, settings["channel_id"], stars)


@starboard.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.command("star", "Handle the starboard.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def star(ctx: SnedSlashContext) -> None:
    pass


@star.child
@lightbulb.option("id", "The ID of the starboard entry. You can find this in the footer.")
@lightbulb.command("show", "Show a starboard entry.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def star_show(ctx: SnedSlashContext, id: str) -> None:

    assert ctx.guild_id is not None

    try:
        orig_id = abs(int(id))
    except (TypeError, ValueError):
        embed = hikari.Embed(
            title="❌ Invalid value",
            description="Expected an integer value for parameter `id`.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed)
        return

    records = await ctx.app.db_cache.get(table="starboard", guild_id=ctx.guild_id, limit=1)

    if not records or not records[0]["is_enabled"]:
        embed = hikari.Embed(
            title="❌ Starboard disabled",
            description="The starboard is not enabled on this server!",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed)
        return

    settings = records[0]

    record = await ctx.app.db.fetchrow(
        "SELECT entry_msg_id, channel_id FROM starboard_entries WHERE orig_msg_id = $1 AND guild_id = $2",
        orig_id,
        ctx.guild_id,
    )

    if not record:
        embed = hikari.Embed(title="❌ Not found", description="Starboard entry not found!", color=const.ERROR_COLOR)
        await ctx.respond(embed=embed)
        return

    message = await ctx.app.rest.fetch_message(settings["channel_id"], record.get("entry_msg_id"))
    await ctx.respond(
        f"Showing entry: `{orig_id}`\n[Jump to entry!]({message.make_link(ctx.guild_id)})", embed=message.embeds[0]
    )


def load(bot: SnedBot) -> None:
    bot.add_plugin(starboard)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(starboard)


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
