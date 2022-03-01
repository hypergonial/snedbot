import ast
import logging
import subprocess
import textwrap
import traceback
import typing as t

import hikari
import lightbulb
import miru
from miru.ext import nav
from models import SnedPrefixContext
from models import AuthorOnlyNavigator
from models.bot import SnedBot
from models.views import AuthorOnlyView
import shlex

logger = logging.getLogger(__name__)

dev = lightbulb.Plugin("Development")
dev.add_checks(lightbulb.owner_only)


class TrashButton(nav.NavButton):
    def __init__(self):
        super().__init__(style=hikari.ButtonStyle.SECONDARY, emoji="🗑️", row=1)

    async def callback(self, ctx: miru.ViewContext) -> None:
        await self.view.message.delete()
        self.view.stop()


class OutputNav(AuthorOnlyNavigator):
    async def on_timeout(self) -> None:
        try:
            return await self.message.delete()
        except hikari.NotFoundError:
            pass


class TrashView(AuthorOnlyView):
    @miru.button(emoji="🗑️", style=hikari.ButtonStyle.SECONDARY)
    async def trash(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        await self.message.delete()
        self.stop()

    async def on_timeout(self) -> None:
        try:
            return await self.message.delete()
        except hikari.NotFoundError:
            pass


def format_output(text: str) -> str:
    # Escape markdown fmt
    return text.replace("```py", "").replace("```ansi", "").replace("`", "´")


async def send_paginated(
    ctx: SnedPrefixContext,
    messageable: hikari.SnowflakeishOr[t.Union[hikari.TextableChannel, hikari.User]],
    text: str,
    *,
    prefix: str = "",
    suffix: str = "",
) -> None:
    """
    Send command output paginated if appropriate.
    """
    text = str(text)
    ctx.get_guild().get_members()
    channel_id = None
    if not isinstance(messageable, hikari.User):
        channel_id = hikari.Snowflake(messageable)

    if len(text) <= 2000:
        if channel_id:
            view = TrashView(ctx, timeout=300)
            message = await ctx.app.rest.create_message(
                channel_id, f"{prefix}{format_output(text)}{suffix}", components=view.build()
            )
            return view.start(message)
        else:
            return await messageable.send(f"{prefix}{format_output(text)}{suffix}")

    buttons = [
        nav.FirstButton(),
        nav.PrevButton(),
        nav.IndicatorButton(),
        nav.NextButton(),
        nav.LastButton(),
        TrashButton(),
    ]
    paginator = lightbulb.utils.StringPaginator(prefix=prefix, suffix=suffix, max_chars=2000)

    for line in text.split("\n"):
        paginator.add_line(format_output(line))

    navmenu = OutputNav(ctx, pages=list(paginator.build_pages()), buttons=buttons, timeout=300)

    if not channel_id:
        channel_id = await messageable.fetch_dm_channel()

    await navmenu.send(channel_id)


async def run_shell(ctx: SnedPrefixContext, code: str) -> None:
    """
    Run code in shell and return output to Discord.
    """
    code: str = str(code)

    code = code.replace("```py", "").replace("`", "").strip()

    await ctx.app.rest.trigger_typing(ctx.channel_id)
    try:
        result = subprocess.run(shlex.split(code), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10.0)
    except subprocess.TimeoutExpired as e:
        await ctx.event.message.add_reaction("❗")
        out = e.stderr or e.stdout
        out = ":\n" + out.decode("utf-8") if out else ""

        return await send_paginated(ctx, ctx.channel_id, "Process timed out" + out, prefix="```ansi\n", suffix="```")

    if result.returncode != 0:
        await ctx.event.message.add_reaction("❗")
        if result.stderr and result.stderr.decode("utf-8"):
            return await send_paginated(
                ctx, ctx.channel_id, result.stderr.decode("utf-8"), prefix="```ansi\n", suffix="```"
            )

    await ctx.event.message.add_reaction("✅")
    if result.stdout and result.stdout.decode("utf-8"):
        await send_paginated(ctx, ctx.channel_id, result.stdout.decode("utf-8"), prefix="```ansi\n", suffix="```")


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
@lightbulb.option("code", "Code to execute.", modifier=lightbulb.OptionModifier.CONSUME_REST)
@lightbulb.command("py", "Run code.")
@lightbulb.implements(lightbulb.PrefixCommand)
async def eval_py(ctx: SnedPrefixContext) -> None:

    globals_dict = {
        "_author": ctx.author,
        "_bot": ctx.bot,
        "_app": ctx.app,
        "_channel": ctx.get_channel(),
        "_guild": ctx.get_guild(),
        "_message": ctx.event.message,
        "_ctx": ctx,
    }
    code: str = ctx.options.code

    code = code.replace("```py", "").replace("`", "").strip()

    # Check if last line is an expression and return it if so
    abstract_syntax_tree = ast.parse(code, filename=f"{ctx.guild_id}{ctx.channel_id}.py")
    node: t.List[ast.stmt] = abstract_syntax_tree.body

    if node and type(node[0]) is ast.Expr:
        code = code.split("\n")
        code[-1] = f"return {code[-1]}"
        code = "\n".join(code)

    code_func = f"async def _container():\n" + textwrap.indent(code, "   ")

    async with ctx.app.rest.trigger_typing(ctx.channel_id):
        try:
            exec(code_func, globals_dict, locals())
            return_value = await locals()["_container"]()

            await ctx.event.message.add_reaction("✅")

            if return_value is not None:
                await send_paginated(ctx, ctx.channel_id, return_value, prefix="```py\n", suffix="```")

        except Exception as e:
            embed = hikari.Embed(
                title="❌ Exception encountered",
                description=f"```{e.__class__.__name__}: {e}```",
                color=ctx.app.error_color,
            )
            try:
                await ctx.event.message.add_reaction("❗")
                await ctx.respond(embed=embed)
            except hikari.ForbiddenError:
                pass

            traceback_msg = "\n".join(traceback.format_exception(type(e), e, e.__traceback__))
            await send_paginated(ctx, ctx.author, traceback_msg, prefix="```py\n", suffix="```")


def load(bot: SnedBot) -> None:
    bot.add_plugin(dev)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(dev)


@dev.command()
@lightbulb.option("code", "Code to execute.", modifier=lightbulb.OptionModifier.CONSUME_REST)
@lightbulb.command("sh", "Run code.")
@lightbulb.implements(lightbulb.PrefixCommand)
async def eval_sh(ctx: SnedPrefixContext) -> None:

    await run_shell(ctx, ctx.options.code)


@dev.command()
@lightbulb.option("code", "Code to execute.", modifier=lightbulb.OptionModifier.CONSUME_REST)
@lightbulb.command("git", "Run git commands.")
@lightbulb.implements(lightbulb.PrefixCommand)
async def dev_git_pull(ctx: SnedPrefixContext) -> None:
    await run_shell(ctx, f"git {ctx.options.code}")


@dev.command()
@lightbulb.command("sync", "Sync application commands.")
@lightbulb.implements(lightbulb.PrefixCommand)
async def resync_app_cmds(ctx: SnedPrefixContext) -> None:
    await ctx.app.rest.trigger_typing(ctx.channel_id)
    await ctx.app.sync_application_commands()
    await ctx.respond("🔃 Synced application commands.")
