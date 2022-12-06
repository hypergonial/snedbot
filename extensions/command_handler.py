from __future__ import annotations

import asyncio
import datetime
import logging
import traceback
import typing as t

import hikari
import lightbulb

from etc import const
from etc.perms_str import get_perm_str
from models import SnedContext
from models.bot import SnedBot
from models.context import SnedPrefixContext, SnedSlashContext
from models.errors import (
    BotRoleHierarchyError,
    InteractionTimeOutError,
    MemberExpectedError,
    RoleHierarchyError,
    UserBlacklistedError,
)
from models.plugin import SnedPlugin
from utils import helpers

logger = logging.getLogger(__name__)

ch = SnedPlugin("Command Handler")


async def log_exc_to_channel(
    error_str: str, ctx: t.Optional[lightbulb.Context] = None, event: t.Optional[hikari.ExceptionEvent] = None
) -> None:
    """Log an exception traceback to the specified logging channel.

    Parameters
    ----------
    error_str : str
        The exception message to print.
    ctx : t.Optional[lightbulb.Context], optional
        The context to use for additional information, by default None
    event : t.Optional[hikari.ExceptionEvent], optional
        The event to use for additional information, by default None
    """

    error_lines = error_str.split("\n")
    paginator = lightbulb.utils.StringPaginator(max_chars=2000, prefix="```py\n", suffix="```")
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
        paginator.add_line(f"Uncaught exception:")

    for line in error_lines:
        paginator.add_line(line)

    assert isinstance(ch.app, SnedBot)
    channel_id = ch.app.config.ERROR_LOGGING_CHANNEL

    if not channel_id:
        return

    for page in paginator.build_pages():
        try:
            await ch.app.rest.create_message(channel_id, page)
        except Exception as error:
            logging.error(f"Failed sending traceback to error-logging channel: {error}")


async def application_error_handler(ctx: SnedContext, error: BaseException) -> None:
    try:
        if isinstance(error, lightbulb.CheckFailure):
            error = error.causes[0] if error.causes else error.__cause__ if error.__cause__ else error

        if isinstance(error, UserBlacklistedError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Application access terminated",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if isinstance(error, lightbulb.MissingRequiredPermission):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Missing Permissions",
                    description=f"You require `{get_perm_str(error.missing_perms).replace('|', ', ')}` permissions to execute this command.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if isinstance(error, lightbulb.BotMissingRequiredPermission):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Bot Missing Permissions",
                    description=f"The bot requires `{get_perm_str(error.missing_perms).replace('|', ', ')}` permissions to execute this command.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if isinstance(error, lightbulb.CommandIsOnCooldown):
            await ctx.respond(
                embed=hikari.Embed(
                    title="🕘 Cooldown Pending",
                    description=f"Please retry in: `{datetime.timedelta(seconds=round(error.retry_after))}`",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if isinstance(error, lightbulb.MaxConcurrencyLimitReached):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Max Concurrency Reached",
                    description=f"You have reached the maximum amount of running instances for this command. Please try again later.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if isinstance(error, BotRoleHierarchyError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Role Hierarchy Error",
                    description=str(error) or "The targeted user's highest role is higher than the bot's highest role.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if isinstance(error, RoleHierarchyError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Role Hierarchy Error",
                    description=str(error) or "The targeted user's highest role is higher than your highest role.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if isinstance(error, lightbulb.CommandInvocationError):

            if isinstance(error.original, asyncio.TimeoutError):
                await ctx.respond(
                    embed=hikari.Embed(
                        title="❌ Action timed out",
                        description=f"This command timed out.",
                        color=const.ERROR_COLOR,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return

            elif isinstance(error.original, hikari.InternalServerError):
                await ctx.respond(
                    embed=hikari.Embed(
                        title="❌ Discord Server Error",
                        description="This action has failed due to an issue with Discord's servers. Please try again in a few moments.",
                        color=const.ERROR_COLOR,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return

            elif isinstance(error.original, hikari.ForbiddenError):
                await ctx.respond(
                    embed=hikari.Embed(
                        title="❌ Forbidden",
                        description=f"This action has failed due to a lack of permissions.\n**Error:** ```{error.original}```",
                        color=const.ERROR_COLOR,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return

            elif isinstance(error.original, RoleHierarchyError):
                await ctx.respond(
                    embed=hikari.Embed(
                        title="❌ Role Hiearchy Error",
                        description=f"This action failed due to trying to modify a user with a role higher or equal to your highest role.",
                        color=const.ERROR_COLOR,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return

            elif isinstance(error.original, BotRoleHierarchyError):
                await ctx.respond(
                    embed=hikari.Embed(
                        title="❌ Role Hiearchy Error",
                        description=f"This action failed due to trying to modify a user with a role higher than the bot's highest role.",
                        color=const.ERROR_COLOR,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return

            if isinstance(error.original, MemberExpectedError):
                await ctx.respond(
                    embed=hikari.Embed(
                        title="❌ Member Expected",
                        description=f"Expected a user who is a member of this server.",
                        color=const.ERROR_COLOR,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return

        assert ctx.command is not None

        logging.error("Ignoring exception in command {}:".format(ctx.command.name))
        exception_msg = "\n".join(traceback.format_exception(type(error), error, error.__traceback__))
        logging.error(exception_msg)
        error = error.original if hasattr(error, "original") else error  # type: ignore

        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Unhandled exception",
                description=f"An error happened that should not have happened. Please [contact us](https://discord.gg/KNKr8FPmJa) with a screenshot of this message!\n**Error:** ```{error.__class__.__name__}: {str(error).replace(ctx.app._token, '')}```",
                color=const.ERROR_COLOR,
            ).set_footer(text=f"Guild: {ctx.guild_id}"),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
    except hikari.NotFoundError:
        raise InteractionTimeOutError(
            f"Interaction timed out while handling error: \n{error.__class__} {error}\nCommand: {ctx.command.name if ctx.command else 'None'}\nGuild: {ctx.guild_id}\nUser: {ctx.user.id}",
        )

    await log_exc_to_channel(exception_msg, ctx)


@ch.listener(lightbulb.UserCommandErrorEvent)
@ch.listener(lightbulb.MessageCommandErrorEvent)
@ch.listener(lightbulb.SlashCommandErrorEvent)
async def application_command_error_handler(event: lightbulb.CommandErrorEvent) -> None:
    assert isinstance(event.context, SnedSlashContext)
    await application_error_handler(event.context, event.exception)


@ch.listener(lightbulb.UserCommandCompletionEvent)
@ch.listener(lightbulb.SlashCommandCompletionEvent)
@ch.listener(lightbulb.MessageCommandCompletionEvent)
async def application_command_completion_handler(event: lightbulb.events.CommandCompletionEvent):
    if event.context.author.id in event.context.app.owner_ids:  # Ignore cooldowns for owner c:
        if cm := event.command.cooldown_manager:
            await cm.reset_cooldown(event.context)


@ch.listener(lightbulb.PrefixCommandErrorEvent)
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
    raise event.exception


@ch.listener(lightbulb.events.CommandInvocationEvent)
async def command_invoke_listener(event: lightbulb.events.CommandInvocationEvent) -> None:
    logger.info(
        f"Command {event.command.name} was invoked by {event.context.author} in guild {event.context.guild_id}."
    )


@ch.listener(lightbulb.PrefixCommandInvocationEvent)
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
    await event.context.event.message.add_reaction("▶️")


@ch.listener(hikari.ExceptionEvent)
async def event_error_handler(event: hikari.ExceptionEvent) -> None:
    logging.error("Ignoring exception in listener {}:".format(event.failed_event.__class__.__name__))
    exception_msg = "\n".join(traceback.format_exception(*event.exc_info))
    logging.error(exception_msg)
    await log_exc_to_channel(exception_msg, event=event)


def load(bot: SnedBot) -> None:
    bot.add_plugin(ch)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(ch)


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
