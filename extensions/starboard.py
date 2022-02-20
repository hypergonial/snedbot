import logging

import hikari
import lightbulb
from models.bot import SnedBot
from utils import helpers
import typing as t
import re

# Mapping of message_id: starboard_message_id
starboard_messages = {}

logger = logging.getLogger(__name__)

starboard = lightbulb.Plugin("Starboard")

image_url_regex = re.compile(
    r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()!@:%_\+.~#?&\/\/=]*)([.]jpe?g|png|gif|bmp|webp)[-a-zA-Z0-9@:%._\+~#=?&]*"
)

STAR_MAPPING = {
    "⭐": 0,
    "🌟": 5,
    "✨": 10,
    "💫": 15,
}


def get_image_urls(content: str) -> t.Optional[t.List[str]]:
    """Return a list of image URLs found in the message content."""

    matches: re.Match = re.search(image_url_regex, content)

    if not matches:
        return None

    return content[matches.span()[0] : matches.span()[1]]


def get_attachment_urls(message: hikari.Message) -> t.Optional[t.List[str]]:
    """Return a list of image attachment URLs found in the message."""

    if not message.attachments:
        return

    attach_urls = [attachment.url for attachment in message.attachments]
    string = " ".join(attach_urls)

    matches: re.Match = re.search(image_url_regex, string)

    if not matches:
        return None

    return string[matches.span()[0] : matches.span()[1]]


def create_starboard_payload(message: hikari.Message, stars: int) -> t.Dict[str, t.Any]:
    """Create message payload for a starboard entry."""

    emoji = [emoji for emoji, value in STAR_MAPPING.items() if value <= stars][-1]
    content = f"{emoji} **{stars}** <#{message.channel_id}>"
    embed = (
        hikari.Embed(description=message.content, color=0xFFC20C)
        .set_author(name=str(message.author), icon=message.author.display_avatar_url)
        .set_footer(f"ID: {message.id}")
    )
    attachments = message.attachments

    if image_urls := get_attachment_urls(message):
        embed.set_image(image_urls)
        attachments = [attachment for attachment in attachments if attachment.url != image_urls]

    elif image_urls := get_image_urls(message.content):
        embed.set_image(image_urls)

    if attachments:
        embed.add_field(
            "Attachments", "\n".join([f"[{attachment.filename}]({attachment.url})" for attachment in attachments])
        )

    if message.referenced_message:
        embed.add_field(
            "Replying to",
            f"[{message.referenced_message.author}]({message.referenced_message.make_link(message.referenced_message.guild_id)})",
        )

    embed.add_field("Original Message", f"[Jump!]({message.make_link(message.guild_id)})")

    return {"content": content, "embed": embed}


async def handle_starboard(
    plugin: lightbulb.Plugin, event: t.Union[hikari.GuildReactionAddEvent, hikari.GuildReactionDeleteEvent]
) -> None:
    """The main starboard logic, creates and updates starboard entries on every reaction event"""

    if not event.is_for_emoji("⭐"):
        return

    records = await plugin.app.db_cache.get(table="starboard", guild_id=event.guild_id)

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
        async with plugin.app.pool.acquire() as con:
            await con.execute("""UPDATE starboard SET channel_id = null WHERE guild_id = $1""", event.guild_id)
            await con.execute("""DELETE FROM starboard_entries WHERE guild_id = $1""", event.guild_id)
        return

    if event.channel_id in settings["excluded_channels"]:
        return

    perms = lightbulb.utils.permissions_in(plugin.app.cache.get_guild_channel(event.channel_id), me)
    if not helpers.includes_permissions(
        perms,
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY,
    ):
        return

    message = await plugin.app.rest.fetch_message(event.channel_id, event.message_id)
    reactions = [reaction for reaction in message.reactions if str(reaction.emoji) == "⭐"]
    if not reactions:
        return

    stars = reactions[0].count

    if stars < settings["star_limit"]:
        return
    starboard_msg_id = starboard_messages.get(event.message_id)
    payload = create_starboard_payload(message, stars)

    if not starboard_msg_id:
        records = await plugin.app.pool.fetch(f"""SELECT * FROM starboard_entries WHERE orig_msg_id = $1""", message.id)

        if not records:
            # Create new entry
            starboard_msg_id = (await plugin.app.rest.create_message(settings["channel_id"], **payload)).id
            starboard_messages[event.message_id] = starboard_msg_id

            await plugin.app.pool.execute(
                """INSERT INTO starboard_entries 
                (guild_id, channel_id, orig_msg_id, entry_msg_id) 
                VALUES ($1, $2, $3, $4)""",
                event.guild_id,
                event.channel_id,
                event.message_id,
                starboard_msg_id,
            )
            return

        else:
            starboard_msg_id = records[0]["entry_msg_id"]
            starboard_messages[event.message_id] = starboard_msg_id

    try:
        await plugin.app.rest.edit_message(settings["channel_id"], starboard_msg_id, **payload)
    except hikari.NotFoundError:
        # Delete entry, re-run logic to create a new starboard entry
        await plugin.app.pool.execute(f"""DELETE FROM starboard_entries WHERE entry_msg_id = $1""", starboard_msg_id)
        starboard_messages.pop(event.message_id, None)
        await handle_starboard(plugin, event)


@starboard.listener(hikari.GuildReactionDeleteEvent, bind=True)
@starboard.listener(hikari.GuildReactionAddEvent, bind=True)
async def on_reaction(
    plugin: lightbulb.Plugin, event: t.Union[hikari.GuildReactionAddEvent, hikari.GuildReactionDeleteEvent]
) -> None:
    await handle_starboard(plugin, event)


def load(bot: SnedBot) -> None:
    bot.add_plugin(starboard)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(starboard)
