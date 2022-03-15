import functools
import operator
import hikari
import lightbulb

from models.context import SnedContext
from utils import helpers
from models.errors import BotRoleHierarchyError, RoleHierarchyError

def _guild_only(ctx: SnedContext) -> bool:
    if not ctx.guild_id:
        raise lightbulb.OnlyInGuild("This command can only be used in a guild.")
    return True

@lightbulb.Check  # type: ignore
async def is_above_target(ctx: SnedContext) -> bool:
    """Check if the targeted user is above the bot's top role or not.
    Used in the moderation extension."""

    if not hasattr(ctx.options, "user"):
        return True

    if not ctx.guild_id:
        return True

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
    assert me is not None

    if isinstance(ctx.options.user, hikari.Member):
        member = ctx.options.user
    else:
        member = ctx.app.cache.get_member(ctx.guild_id, ctx.options.user)

    if not member:
        return True

    if helpers.is_above(me, member):
        return True

    raise BotRoleHierarchyError("Target user top role is higher than bot.")


@lightbulb.Check  # type: ignore
async def is_invoker_above_target(ctx: SnedContext) -> bool:
    """Check if the targeted user is above the invoker's top role or not.
    Used in the moderation extension."""

    if not hasattr(ctx.options, "user"):
        return True

    if not ctx.member or not ctx.guild_id:
        return True

    guild = ctx.get_guild()
    assert guild is not None

    if ctx.member.id == guild.owner_id:
        return True

    if isinstance(ctx.options.user, hikari.Member):
        member = ctx.options.user
    else:
        member = ctx.app.cache.get_member(ctx.guild_id, ctx.options.user)

    if not member:
        return True

    if helpers.is_above(ctx.member, member):
        return True

    raise RoleHierarchyError("Target user top role is higher than author.")


async def _has_permissions(ctx: SnedContext, *, perms: hikari.Permissions) -> bool:
    _guild_only(ctx)
    try:
        channel, guild = (ctx.get_channel() or await ctx.app.rest.fetch_channel(ctx.channel_id)), ctx.get_guild()
    except hikari.ForbiddenError:
        raise lightbulb.BotMissingRequiredPermission("Check cannot run due to missing permissions.", perms=hikari.Permissions.VIEW_CHANNEL)

    if guild is None:
        raise lightbulb.InsufficientCache("Some objects required for this check could not be resolved from the cache.")
    if guild.owner_id == ctx.author.id:
        return True
    
    assert ctx.member is not None

    if isinstance(channel, hikari.GuildThreadChannel):
        channel = ctx.app.cache.get_guild_channel(channel.parent_id)
    
    assert isinstance(channel, hikari.GuildChannel)

    missing_perms = ~lightbulb.utils.permissions_in(channel, ctx.member) & perms
    if missing_perms is not hikari.Permissions.NONE:
        raise lightbulb.MissingRequiredPermission("You are missing one or more permissions required in order to run this command", perms=missing_perms)
    
    return True

async def _bot_has_permissions(ctx: SnedContext, *, perms: hikari.Permissions) -> bool:
    _guild_only(ctx)
    try:
        channel, guild = (ctx.get_channel() or await ctx.app.rest.fetch_channel(ctx.channel_id)), ctx.get_guild()
    except hikari.ForbiddenError:
        raise lightbulb.BotMissingRequiredPermission("Check cannot run due to missing permissions.", perms=hikari.Permissions.VIEW_CHANNEL)

    if guild is None:
        raise lightbulb.InsufficientCache("Some objects required for this check could not be resolved from the cache.")
    member = guild.get_my_member()
    if member is None:
        raise lightbulb.InsufficientCache("Some objects required for this check could not be resolved from the cache.")
    if guild.owner_id == ctx.author.id:
        return True

    if isinstance(channel, hikari.GuildThreadChannel):
        channel = ctx.app.cache.get_guild_channel(channel.parent_id)
    
    assert isinstance(channel, hikari.GuildChannel)

    missing_perms = ~lightbulb.utils.permissions_in(channel, member) & perms
    if missing_perms is not hikari.Permissions.NONE:
        raise lightbulb.MissingRequiredPermission("The bot is missing one or more permissions required in order to run this command", perms=missing_perms)
    
    return True

def has_permissions(perm1: hikari.Permissions, *perms: hikari.Permissions) -> lightbulb.Check:
    """Just a shitty attempt at making has_guild_permissions fetch the channel if it is not present."""
    reduced = functools.reduce(operator.or_, [perm1, *perms])
    return lightbulb.Check(functools.partial(_has_permissions, perms=reduced))

def bot_has_permissions(perm1: hikari.Permissions, *perms: hikari.Permissions) -> lightbulb.Check:
    """Just a shitty attempt at making bot_has_guild_permissions fetch the channel if it is not present."""
    reduced = functools.reduce(operator.or_, [perm1, *perms])
    return lightbulb.Check(functools.partial(_bot_has_permissions, perms=reduced))
