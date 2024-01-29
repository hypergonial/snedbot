import typing as t

import arc
import hikari

from src.models.errors import BotRoleHierarchyError, RoleHierarchyError, UserBlacklistedError
from src.utils import helpers

if t.TYPE_CHECKING:
    from src.models.client import SnedContext  # noqa: TCH004


async def is_not_blacklisted(ctx: SnedContext) -> None:
    """Hook to evaluate if the user is blacklisted or not.

    Parameters
    ----------
    ctx : SnedContext
        The context to evaluate under.

    Returns
    -------
    bool
        A boolean determining if the user is blacklisted or not.

    Raises
    ------
    UserBlacklistedError
        The user is blacklisted.
    """
    records = await ctx.client.db_cache.get(table="blacklist", user_id=ctx.user.id)

    if not records:
        return

    raise UserBlacklistedError("User is blacklisted from using the application.")


async def is_above_target(ctx: SnedContext) -> None:
    """Check if the targeted user is above the bot's top role or not.
    Used in the moderation extension.
    """
    user = ctx.get_option("user", arc.OptionType.USER)

    if not user:
        return

    if not ctx.guild_id:
        return

    guild = ctx.get_guild()
    if guild and guild.owner_id == user.id:
        raise BotRoleHierarchyError("Cannot execute on the owner of the guild.")

    me = ctx.client.cache.get_member(ctx.guild_id, ctx.client.user_id)
    assert me is not None

    member = user if isinstance(user, hikari.Member) else ctx.client.cache.get_member(ctx.guild_id, user)

    if not member:
        return

    if helpers.is_above(me, member):
        return

    raise BotRoleHierarchyError("The targeted user's highest role is higher than the bot's highest role.")


async def is_invoker_above_target(ctx: SnedContext) -> None:
    """Check if the targeted user is above the invoker's top role or not.
    Used in the moderation extension.
    """
    user = ctx.get_option("user", arc.OptionType.USER)

    if not user:
        return

    if not ctx.member or not ctx.guild_id:
        return

    guild = ctx.get_guild()
    assert guild is not None

    if ctx.member.id == guild.owner_id:
        return

    member = user if isinstance(user, hikari.Member) else ctx.client.cache.get_member(ctx.guild_id, user)

    if not member:
        return

    if helpers.is_above(ctx.member, member):
        return

    raise RoleHierarchyError


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
