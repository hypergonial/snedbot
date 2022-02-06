import asyncio
import datetime
import re
from typing import Optional, TypeVar, Union, List, Any

import hikari
import lightbulb
from lightbulb.utils.parser import CONVERTER_TYPE_MAPPING
import miru

import models
from models import errors


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


def utcnow() -> datetime.datetime:
    """
    A short-hand function to return a timezone-aware utc datetime.
    """
    return datetime.datetime.now(datetime.timezone.utc)


def add_embed_footer(embed: hikari.Embed, invoker: hikari.Member) -> hikari.Embed:
    """
    Add a note about the command invoker in the embed passed.
    """
    avatar_url = invoker.display_avatar_url

    embed.set_footer(text=f"Requested by {invoker}", icon=avatar_url)
    return embed


def get_display_avatar(member: hikari.Member) -> str:
    """
    Gets the currently displayed avatar for the member, returns the URL.
    """
    if member.guild_avatar_url:
        return member.guild_avatar_url

    elif member.avatar_url:
        return member.avatar_url

    else:
        return member.default_avatar_url


def get_avatar(user: Union[hikari.User, hikari.Member]) -> str:
    """
    Return the avatar of the specified user, fallback to default_avatar if not found.
    """
    if user.avatar_url:
        return user.avatar_url
    else:
        return user.default_avatar_url


def get_color(member: hikari.Member) -> hikari.Color:
    roles = member.get_roles().__reversed__()
    if roles:
        for role in roles:
            if role.color != hikari.Color.from_rgb(0, 0, 0):
                return role.color

    return hikari.Color.from_rgb(0, 0, 0)


def is_above(me: hikari.Member, member: hikari.Member) -> bool:
    """
    Returns True if me's top role's position is higher than the specified member's.
    """
    if me.get_top_role().position > member.get_top_role().position:
        return True
    return False


def can_harm(
    me: hikari.Member, member: hikari.Member, permission: hikari.Permissions, *, raise_error: bool = False
) -> bool:
    """
    Returns True if "member" can be harmed by "me", also checks if "me" has "permission".
    """

    perms = lightbulb.utils.permissions_for(me)

    if not (perms & permission):
        if raise_error:
            raise lightbulb.BotMissingRequiredPermission(perms=permission)
        return False

    if not is_above(me, member):
        if raise_error:
            raise errors.RoleHierarchyError
        return False

    return True


def get_jump_url(message: hikari.Message):
    """
    Get jump URL for a message.
    """
    guild_id = "@me" if not message.guild_id else message.guild_id
    return f"https://discord.com/channels/{guild_id}/{message.channel_id}/{message.id}"


def is_url(string: str) -> bool:
    """
    Returns True if the provided string is an URL, otherwise False.
    """
    url_regex = re.compile(
        r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()!@:%_\+.~#?&\/\/=]*)"
    )
    if url_regex.fullmatch(string):
        return True
    return False


def get_or_fetch_user(bot: hikari.GatewayBot, user_id: int):
    user = bot.cache.get_user(user_id)
    if not user:
        bot.rest.fetch_user(user_id)
    return user


async def resolve_response(response: Union[lightbulb.ResponseProxy, hikari.Message]) -> hikari.Message:
    """
    Resolve a potential ResponseProxy into a hikari message object. If a hikari.Message is passed, it is returned directly.
    """
    if isinstance(response, hikari.Message):
        return response
    elif isinstance(response, lightbulb.ResponseProxy):
        return await response.message()
    else:
        raise TypeError(f"response must be of type hikari.Message or lightbulb.ResponseProxy, not {type(response)}")


T = TypeVar("T")


async def ask(
    ctx: lightbulb.Context,
    *,
    options: List[miru.SelectOption],
    return_type: T,
    embed_or_content: Union[str, hikari.Embed],
    placeholder: str = None,
    ignore: Optional[List[Any]] = None,
    message: Optional[hikari.Message] = None,
) -> Union[T, Any]:
    """A function that abstracts away the limitations of select menus
    by falling back to a text input from the user if limits are exceeded.

    Parameters
    ----------
    ctx : lightbulb.Context
        The lightbulb context to use for converters.
    options : List[miru.SelectOption]
        A list of select options to use, if not falling back for text input.
    return_type : T
        The expected return type, an appropriate converter will be used.
    embed_or_content : Union[str, hikari.Embed]
        The embed or content to use for the prompt.
    placeholder : str, optional
        The select menu's placeholder, by default None
    ignore : List[Any], optional
        Return values to skip conversion for, by default None
    message : Optional[hikari.Message], optional
        If provided, a message to edit, by default None

    Returns
    -------
    Union[T, Any]
        An object corresponding to the specified return type, or raw value if in ignore.

    Raises
    ------
    TypeError
        An invalid return_type was provided or conversion to it failed.
    asyncio.TimeoutError
        Timed out without a response.
    """
    if return_type not in CONVERTER_TYPE_MAPPING.keys():
        return TypeError(
            f"return_type must be of types: {' '.join(list(CONVERTER_TYPE_MAPPING.keys()))}, not {return_type}"
        )

    # Get appropiate converter for return type
    converter: lightbulb.BaseConverter = CONVERTER_TYPE_MAPPING[return_type](ctx)

    # If the select will result in a Bad Request or not
    invalid_select: bool = False
    if len(options) > 25:
        invalid_select = True
    else:
        for option in options:
            if len(option.label) > 25 or (option.description and len(option.description) > 100):
                invalid_select = True

    if isinstance(embed_or_content, str):
        content = embed_or_content
        embeds = []
    elif isinstance(embed_or_content, hikari.Embed):
        content = ""
        embeds = [embed_or_content]
    else:
        raise TypeError(f"embed_or_content must be of type str or hikari.Embed, not {type(embed_or_content)}")

    if not invalid_select:
        view = models.AuthorOnlyView(ctx)
        view.add_item(models.StopSelect(placeholder=placeholder, options=options))

        if message:
            message = await message.edit(content=content, embeds=embeds, components=view.build())
        else:
            response = await ctx.respond(content=content, embeds=embeds, components=view.build())
            message = await resolve_response(response)

        view.start(message)
        await view.wait()
        if view.children[0].values:
            if view.children[0].values[0] in ignore:
                return view.children[0].values[0]
            return await converter.convert(view.children[0].values[0])

        raise asyncio.TimeoutError("View timed out without response.")

    else:
        if embeds:
            embeds[0].description = f"{embeds[0].description}\n\nPlease type your response below!"
        elif content:
            content = f"{content}\n\nPlease type your response below!"

        predicate = lambda e: e.author_id == ctx.author.id and e.channel_id == ctx.channel_id

        event = await ctx.app.wait_for(hikari.MessageCreateEvent, timeout=120.0, predicate=predicate)
        if event.content:
            if event.content in ignore:
                return event.content
            return await converter.convert(event.content)


async def maybe_delete(message: hikari.Message) -> None:
    try:
        await message.delete()
    except:
        pass


async def maybe_edit(message: hikari.Message, *args, **kwargs) -> None:
    try:
        return await message.edit(*args, **kwargs)
    except:
        pass


def format_reason(
    reason: str = None, moderator: Optional[hikari.Member] = None, *, max_length: Optional[int] = 512
) -> str:
    """
    Format a reason for a moderation action
    """
    if not reason:
        reason = "No reason provided."

    if moderator:
        reason = f"{moderator} ({moderator.id}): {reason}"

    if max_length and len(reason) > max_length:
        reason = reason[: max_length - 3] + "..."

    return reason
