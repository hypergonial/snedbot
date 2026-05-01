from __future__ import annotations

import asyncio
import datetime
import logging
import traceback
import typing as t

import arc
import hikari
from miru.ext import nav

from src.etc import const
from src.etc.perms_str import get_perm_str
from src.models.client import SnedClient, SnedContext, SnedPlugin
from src.models.errors import (
    BotRoleHierarchyError,
    InteractionTimeOutError,
    MemberExpectedError,
    RoleHierarchyError,
    UserBlacklistedError,
)

logger = logging.getLogger(__name__)

plugin = SnedPlugin("Command Handler")


async def log_exc_to_channel(
    error_str: str, ctx: SnedContext | None = None, event: hikari.ExceptionEvent[t.Any] | None = None
) -> None:
    """Log an exception traceback to the specified logging channel.

    Parameters
    ----------
    error_str : str
        The exception message to print.
    ctx : lightbulb.Context, optional
        The context to use for additional information, by default None
    event : hikari.ExceptionEvent, optional
        The event to use for additional information, by default None
    """
    error_lines = error_str.split("\n")
    paginator = nav.utils.Paginator(max_len=2000, prefix="```py\n", suffix="```")
    if ctx:
        if guild := ctx.get_guild():
            assert ctx.command is not None
            paginator.add_line(
                f"Error in '{guild.name}' ({ctx.guild_id}) during command '{ctx.command.name}' executed by user '{ctx.author}' ({ctx.author.id})\n"
            )

    elif event:
        paginator.add_line(
            f"Ignoring exception in listener for {event.failed_event.__class__.__name__}, callback {event.failed_callback.__name__}:\n"
        )
    else:
        paginator.add_line("Uncaught exception:")

    for line in error_lines:
        paginator.add_line(line)

    channel_id = plugin.client.config.ERROR_LOGGING_CHANNEL

    if not channel_id:
        return

    for page in paginator.pages:
        try:
            await plugin.client.rest.create_message(channel_id, page)
        except Exception as error:
            logger.error(f"Failed sending traceback to error-logging channel: {error}")


async def application_error_handler(ctx: SnedContext, error: BaseException) -> None:
    try:
        if isinstance(error, UserBlacklistedError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Application access terminated",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, arc.InvokerMissingPermissionsError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Missing Permissions",
                    description=f"You require `{get_perm_str(error.missing_permissions).replace('|', ', ')}` permissions to execute this command.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, arc.BotMissingPermissionsError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Bot Missing Permissions",
                    description=f"The bot requires `{get_perm_str(error.missing_permissions).replace('|', ', ')}` permissions to execute this command.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, arc.UnderCooldownError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="🕘 Cooldown Pending",
                    description=f"Please retry in: `{datetime.timedelta(seconds=round(error.retry_after))}`",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, arc.MaxConcurrencyReachedError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Max Concurrency Reached",
                    description="You have reached the maximum amount of running instances for this command. Please try again later.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, BotRoleHierarchyError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Role Hierarchy Error",
                    description=str(error) or "The targeted user's highest role is higher than the bot's highest role.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, RoleHierarchyError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Role Hierarchy Error",
                    description=str(error) or "The targeted user's highest role is higher than your highest role.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, asyncio.TimeoutError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Action timed out",
                    description="This command timed out.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, hikari.InternalServerError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Discord Server Error",
                    description="This action has failed due to an issue with Discord's servers. Please try again in a few moments.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, hikari.ForbiddenError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Forbidden",
                    description=f"This action has failed due to a lack of permissions.\n**Error:** ```{error}```",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, RoleHierarchyError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Role Hiearchy Error",
                    description="This action failed due to trying to modify a user with a role higher or equal to your highest role.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, BotRoleHierarchyError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Role Hiearchy Error",
                    description="This action failed due to trying to modify a user with a role higher than the bot's highest role.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        elif isinstance(error, MemberExpectedError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Member Expected",
                    description="Expected a user who is a member of this server.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        elif isinstance(error, arc.OptionConverterFailureError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Option Conversion Error",
                    description=f"Failed to convert option `{error.option.name}` to `{error.option.option_type}`.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
        else:
            logger.error("Ignoring exception in command {}:".format(ctx.command.name))
            exception_msg = "\n".join(traceback.format_exception(type(error), error, error.__traceback__))
            logger.error(exception_msg)

            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Unhandled exception",
                    description=f"An error happened that should not have happened. Please [contact us](https://discord.gg/KNKr8FPmJa) with a screenshot of this message!\n**Error:** ```{error.__class__.__name__}: {str(error).replace(ctx.client.app._token, '')}```",
                    color=const.ERROR_COLOR,
                ).set_footer(text=f"Guild: {ctx.guild_id}"),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            await log_exc_to_channel(exception_msg, ctx)
    except hikari.NotFoundError:
        raise InteractionTimeOutError(
            f"Interaction timed out while handling error: \n{error.__class__} {error}\nCommand: {ctx.command.name if ctx.command else 'None'}\nGuild: {ctx.guild_id}\nUser: {ctx.user.id}",
        )


@plugin.listen(arc.CommandErrorEvent)
async def command_error_handler(event: arc.CommandErrorEvent[t.Any]) -> None:
    await application_error_handler(event.context, event.exception)


async def client_post_hook(ctx: SnedContext) -> None:
    if ctx.author.id in ctx.client.owner_ids:
        ctx.command.reset_all_limiters(ctx)


""" @plugin.listener(lightbulb.PrefixCommandErrorEvent)
async def prefix_error_handler(event: lightbulb.PrefixCommandErrorEvent) -> None:
    if event.context.author.id not in event.app.owner_ids:
        return
    if isinstance(event.exception, lightbulb.CheckFailure):
        return
    if isinstance(event.exception, lightbulb.CommandNotFound):
        return

    error = event.exception.original if hasattr(event.exception, "original") else event.exception  # type: ignore

    await event.context.respond(
        embed=hikari.Embed(
            title="❌ Exception encountered",
            description=f"```{error}```",
            color=const.ERROR_COLOR,
        )
    )
    raise event.exception """

""" @plugin.listener(lightbulb.PrefixCommandInvocationEvent)
async def prefix_command_invoke_listener(event: lightbulb.PrefixCommandInvocationEvent) -> None:
    if event.context.author.id not in event.app.owner_ids:
        return

    if event.context.guild_id:
        assert isinstance(event.app, SnedBot)
        me = event.app.cache.get_member(event.context.guild_id, event.app.user_id)
        assert me is not None

        if not helpers.includes_permissions(lightbulb.utils.permissions_for(me), hikari.Permissions.ADD_REACTIONS):
            return

    assert isinstance(event.context, SnedPrefixContext)
    await event.context.event.message.add_reaction("▶️") """


async def on_command_invoke(ctx: SnedContext) -> None:
    logger.info(
        f"Command '{' '.join(ctx.command.qualified_name)}' was invoked by '{ctx.author}' in guild {ctx.guild_id}."
    )


@plugin.listen()
async def event_error_handler(event: hikari.ExceptionEvent[t.Any]) -> None:
    logging.error("Ignoring exception in listener {}:".format(event.failed_event.__class__.__name__))
    exception_msg = "\n".join(traceback.format_exception(*event.exc_info))
    logging.error(exception_msg)
    await log_exc_to_channel(exception_msg, event=event)


@arc.loader
def load(client: SnedClient) -> None:
    client.add_plugin(plugin)
    client.add_hook(on_command_invoke)
    client.add_post_hook(client_post_hook)
    client.set_error_handler(application_error_handler)


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
