from __future__ import annotations

import asyncio
import datetime
import logging
import traceback
import typing as t

import hikari
import lightbulb

from etc import constants as const
from etc.perms_str import get_perm_str
from models import SnedContext
from models.bot import SnedBot
from models.errors import (BotRoleHierarchyError, MemberExpectedError,
                           RoleHierarchyError)

logger = logging.getLogger(__name__)

ch = lightbulb.Plugin("Command Handler")


async def log_error_to_homeguild(
    error_str: str, ctx: t.Optional[lightbulb.Context] = None, event: t.Optional[hikari.Event] = None
) -> None:

    error_lines = error_str.split("\n")
    paginator = lightbulb.utils.StringPaginator(max_chars=2000, prefix="```py\n", suffix="```")

    if ctx and ctx.get_guild():
        paginator.add_line(
            f"Error in '{ctx.get_guild().name}' ({ctx.guild_id}) during command '{ctx.command.name}' executed by user '{ctx.author}' ({ctx.author.id})\n"
        )

    elif event:
        paginator.add_line(f"Ignoring exception in listener for {event.__class__.__name__}:\n")
    else:
        paginator.add_line(f"Uncaught exception:")

    for line in error_lines:
        paginator.add_line(line)

    assert isinstance(ctx.app, SnedBot)
    channel_id = ctx.app.config.ERROR_LOGGING_CHANNEL

    if not channel_id:
        return

    for page in paginator.build_pages():
        try:
            await ctx.app.rest.create_message(channel_id, page)
        except Exception as error:
            logging.error(f"Failed sending traceback to error-logging channel: {error}")


async def application_error_handler(ctx: SnedContext, error: lightbulb.LightbulbError) -> None:

    if isinstance(error, lightbulb.CheckFailure):

        if isinstance(error, lightbulb.MissingRequiredPermission):
            embed = hikari.Embed(
                title="❌ Missing Permissions",
                description=f"You require `{get_perm_str(error.missing_perms).replace('|', ', ')}` permissions to execute this command.",
                color=const.ERROR_COLOR,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        elif isinstance(error, lightbulb.BotMissingRequiredPermission):
            embed = hikari.Embed(
                title="❌ Bot Missing Permissions",
                description=f"The bot requires `{get_perm_str(error.missing_perms).replace('|', ', ')}` permissions to execute this command.",
                color=const.ERROR_COLOR,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    if isinstance(error, lightbulb.CommandIsOnCooldown):
        embed = hikari.Embed(
            title="🕘 Cooldown Pending",
            description=f"Please retry in: `{datetime.timedelta(seconds=round(error.retry_after))}`",
            color=const.ERROR_COLOR,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    if isinstance(error, lightbulb.CommandInvocationError):

        if isinstance(error.original, asyncio.TimeoutError):
            embed = hikari.Embed(
                title="❌ Action timed out",
                description=f"This command timed out.",
                color=const.ERROR_COLOR,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        elif isinstance(error.original, hikari.InternalServerError):
            embed = hikari.Embed(
                title="❌ Discord Server Error",
                description="This action has failed due to an issue with Discord's servers. Please try again in a few moments.",
                color=const.ERROR_COLOR,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        elif isinstance(error.original, hikari.ForbiddenError):
            embed = hikari.Embed(
                title="❌ Forbidden",
                description=f"This action has failed due to a lack of permissions.\n**Error:** ```{error.original}```",
                color=const.ERROR_COLOR,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        elif isinstance(error.original, RoleHierarchyError):
            embed = hikari.Embed(
                title="❌ Role Hiearchy Error",
                description=f"This action failed due to trying to modify a user with a role higher or equal to your highest role.",
                color=const.ERROR_COLOR,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        elif isinstance(error.original, BotRoleHierarchyError):
            embed = hikari.Embed(
                title="❌ Role Hiearchy Error",
                description=f"This action failed due to trying to modify a user with a role higher than the bot's highest role.",
                color=const.ERROR_COLOR,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        if isinstance(error.original, MemberExpectedError):
            embed = hikari.Embed(
                title="❌ Member Expected",
                description=f"Expected a user who is a member of this server.",
                color=const.ERROR_COLOR,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    logging.error("Ignoring exception in command {}:".format(ctx.command.name))
    exception_msg = "\n".join(traceback.format_exception(type(error), error, error.__traceback__))
    logging.error(exception_msg)
    error = error.original if hasattr(error, "original") else error

    embed = hikari.Embed(
        title="❌ Unhandled exception",
        description=f"An error happened that should not have happened. Please [contact us](https://discord.gg/KNKr8FPmJa) with a screenshot of this message!\n**Error:** ```{error.__class__.__name__}: {error}```",
        color=const.ERROR_COLOR,
    )
    embed.set_footer(text=f"Guild: {ctx.guild_id}")
    await log_error_to_homeguild(exception_msg, ctx)

    await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@ch.listener(lightbulb.UserCommandErrorEvent)
@ch.listener(lightbulb.MessageCommandErrorEvent)
@ch.listener(lightbulb.SlashCommandErrorEvent)
async def slash_error_handler(event: lightbulb.CommandErrorEvent) -> None:
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
    if isinstance(event.exception, lightbulb.CheckFailure):
        return

    error = event.exception.original if hasattr(event.exception, "original") else event.exception

    embed = hikari.Embed(
        title="❌ Exception encountered",
        description=f"```{error}```",
        color=event.context.app.error_color,
    )
    await event.context.respond(embed=embed)
    raise event.exception


@ch.listener(lightbulb.events.CommandInvocationEvent)
async def command_invoke_listener(event: lightbulb.events.CommandInvocationEvent) -> None:
    logger.info(
        f"Command {event.command.name} was invoked by {event.context.author} in guild {event.context.guild_id}."
    )


def load(bot: SnedBot) -> None:
    bot.add_plugin(ch)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(ch)
