import asyncio
import logging

import hikari
import lightbulb
import miru
from miru.ext import nav
from models.bot import SnedBot
from utils import helpers
import perspective
from models import SnedPrefixContext

logger = logging.getLogger(__name__)

dev = lightbulb.Plugin("Development")
dev.add_checks(lightbulb.owner_only)


@dev.command()
@lightbulb.option("extension_name", "The name of the extension to reload.")
@lightbulb.command("reload", "Reload an extension.")
@lightbulb.implements(lightbulb.PrefixCommand)
async def reload_cmd(ctx: SnedPrefixContext) -> None:
    ctx.app.reload_extensions(ctx.options.extension_name)
    await ctx.respond(f"🔃 `{ctx.options.extension_name}`")


@dev.command()
@lightbulb.option("extension_name", "The name of the extension to load.")
@lightbulb.command("load", "Load an extension.")
@lightbulb.implements(lightbulb.PrefixCommand)
async def load_cmd(ctx: SnedPrefixContext) -> None:
    ctx.app.load_extensions(ctx.options.extension_name)
    await ctx.respond(f"📥 `{ctx.options.extension_name}`")


@dev.command()
@lightbulb.option("extension_name", "The name of the extension to unload.")
@lightbulb.command("unload", "Unload an extension.")
@lightbulb.implements(lightbulb.PrefixCommand)
async def unload_cmd(ctx: SnedPrefixContext) -> None:
    ctx.app.unload_extensions(ctx.options.extension_name)
    await ctx.respond(f"📤 `{ctx.options.extension_name}`")


@dev.command()
@lightbulb.option("code", "Code to execute.")
@lightbulb.command("py", "Run code.")
@lightbulb.implements(lightbulb.PrefixCommand)
async def eval_py(ctx: SnedPrefixContext) -> None:

    var_dict = {
        "_author": ctx.author,
        "_bot": ctx.bot,
        "_app": ctx.app,
        "_channel": ctx.get_channel(),
        "_guild": ctx.get_guild(),
        "_message": ctx.event.message,
        "_ctx": ctx,
    }


def load(bot: SnedBot) -> None:
    bot.add_plugin(dev)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(dev)
