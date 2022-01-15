import datetime
from typing import Optional

import hikari


def format_dt(time: datetime.datetime, style: Optional[str] = None) -> str:
    """
    Convert a datetime into a Discord timestamp.
    For styling see this link: https://discord.com/developers/docs/reference#message-formatting-timestamp-styles
    """
    valid_styles = ["t", "T", "d", "D", "f", "F", "R"]

    if style and style not in valid_styles:
        raise ValueError(f"Invalid style passed. Valid styles: {' '.join(valid_styles)}")

    if style:
        return f"<t:{int(time.timestamp())}:{style}>"

    return f"<t:{int(time.timestamp())}>"


def add_embed_footer(embed: hikari.Embed, invoker: hikari.Member) -> hikari.Embed:
    """
    Add a note about the command invoker in the embed passed.
    """
    if invoker.guild_avatar_url:
        avatar_url = invoker.guild_avatar_url
    elif invoker.avatar_url:
        avatar_url = invoker.avatar_url
    else:
        avatar_url = invoker.default_avatar_url

    embed.set_footer(text=f"Requested by {invoker}", icon=avatar_url)
    return embed


def get_jump_url(message: hikari.Message):
    """
    Get jump URL for a message.
    """
    print(message.guild_id)
    guild_id = "@me" if not message.guild_id else message.guild_id
    return f"https://discord.com/channels/{guild_id}/{message.channel_id}/{message.id}"


def get_or_fetch_user(bot: hikari.GatewayBot, user_id: int):
    user = bot.cache.get_user(user_id)
    if not user:
        bot.rest.fetch_user(user_id)
    return user
