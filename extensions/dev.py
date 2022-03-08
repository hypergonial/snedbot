import ast
import logging
import os
import shlex
import subprocess
import textwrap
import traceback
import typing as t

import hikari
import lightbulb
import miru
from miru.ext import nav

from etc import constants as const
from models import AuthorOnlyNavigator, SnedPrefixContext
from models.bot import SnedBot
from models.views import AuthorOnlyView

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
            assert self.message is not None
            return await self.message.delete()
        except hikari.NotFoundError:
            pass


class TrashView(AuthorOnlyView):
    @miru.button(emoji="🗑️", style=hikari.ButtonStyle.SECONDARY)
    async def trash(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        assert self.message is not None
        await self.message.delete()
        self.stop()

    async def on_timeout(self) -> None:
        try:
            assert self.message is not None
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
            assert isinstance(messageable, (hikari.TextableChannel, hikari.User))
            await messageable.send(f"{prefix}{format_output(text)}{suffix}")
            return

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
        assert isinstance(messageable, hikari.User)
        channel_id = await messageable.fetch_dm_channel()

    await navmenu.send(channel_id)


async def run_shell(ctx: SnedPrefixContext, code: str) -> None:
    """
    Run code in shell and return output to Discord.
    """

    code = str(code).replace("```py", "").replace("`", "").strip()

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
@lightbulb.command("reload", "Reload an extension.", pass_options=True)
@lightbulb.implements(lightbulb.PrefixCommand)
async def reload_cmd(ctx: SnedPrefixContext, extension_name: str) -> None:
    ctx.app.reload_extensions(extension_name)
    await ctx.respond(f"🔃 `{extension_name}`")


@dev.command()
@lightbulb.option("extension_name", "The name of the extension to load.")
@lightbulb.command("load", "Load an extension.", pass_options=True)
@lightbulb.implements(lightbulb.PrefixCommand)
async def load_cmd(ctx: SnedPrefixContext, extension_name: str) -> None:
    ctx.app.load_extensions(extension_name)
    await ctx.respond(f"📥 `{extension_name}`")


@dev.command()
@lightbulb.option("extension_name", "The name of the extension to unload.")
@lightbulb.command("unload", "Unload an extension.", pass_options=True)
@lightbulb.implements(lightbulb.PrefixCommand)
async def unload_cmd(ctx: SnedPrefixContext, extension_name: str) -> None:
    ctx.app.unload_extensions(extension_name)
    await ctx.respond(f"📤 `{extension_name}`")


@dev.command()
@lightbulb.option("code", "Code to execute.", modifier=lightbulb.OptionModifier.CONSUME_REST)
@lightbulb.command("py", "Run code.", pass_options=True)
@lightbulb.implements(lightbulb.PrefixCommand)
async def eval_py(ctx: SnedPrefixContext, code: str) -> None:

    globals_dict = {
        "_author": ctx.author,
        "_bot": ctx.bot,
        "_app": ctx.app,
        "_channel": ctx.get_channel(),
        "_guild": ctx.get_guild(),
        "_message": ctx.event.message,
        "_ctx": ctx,
    }

    code = code.replace("```py", "").replace("`", "").strip()

    # Check if last line is an expression and return it if so
    abstract_syntax_tree = ast.parse(code, filename=f"{ctx.guild_id}{ctx.channel_id}.py")
    node: t.List[ast.stmt] = abstract_syntax_tree.body

    if node and type(node[0]) is ast.Expr:
        code_split = code.split("\n")
        code_split[-1] = f"return {code_split[-1]}"
        code = "\n".join(code_split)

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
                color=const.ERROR_COLOR,
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
@lightbulb.command("sh", "Run code.", pass_options=True)
@lightbulb.implements(lightbulb.PrefixCommand)
async def eval_sh(ctx: SnedPrefixContext, code: str) -> None:

    await run_shell(ctx, code)


@dev.command()
@lightbulb.option("code", "Code to execute.", modifier=lightbulb.OptionModifier.CONSUME_REST)
@lightbulb.command("git", "Run git commands.", pass_options=True)
@lightbulb.implements(lightbulb.PrefixCommand)
async def dev_git_pull(ctx: SnedPrefixContext, code: str) -> None:
    await run_shell(ctx, f"git {code}")


@dev.command()
@lightbulb.command("sync", "Sync application commands.")
@lightbulb.implements(lightbulb.PrefixCommand)
async def resync_app_cmds(ctx: SnedPrefixContext) -> None:
    await ctx.app.rest.trigger_typing(ctx.channel_id)
    await ctx.app.sync_application_commands()
    await ctx.respond("🔃 Synced application commands.")


@dev.command()
@lightbulb.command("sql", "Execute an SQL file")
@lightbulb.implements(lightbulb.PrefixCommand)
async def run_sql(ctx: SnedPrefixContext) -> None:
    if not ctx.attachments or not ctx.attachments[0].filename.endswith(".sql"):
        embed = hikari.Embed(
            title="❌ No valid attachment",
            description=f"Expected a singular `.sql` file as attachment with `UTF-8` encoding!",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed)
        return

    await ctx.app.rest.trigger_typing(ctx.channel_id)
    sql: str = (await ctx.attachments[0].read()).decode("utf-8")
    return_value = await ctx.app.pool.execute(sql)
    await ctx.event.message.add_reaction("✅")
    await send_paginated(ctx, ctx.channel_id, str(return_value), prefix="```sql\n", suffix="```")


@dev.command()
@lightbulb.command("shutdown", "Shut down the bot.")
@lightbulb.implements(lightbulb.PrefixCommand)
async def shutdown_cmd(ctx: SnedPrefixContext) -> None:
    confirm_payload = {"content": f"⚠️ Shutting down...", "components": []}
    cancel_payload = {"content": "❌ Shutdown cancelled", "components": []}
    confirmed = await ctx.confirm(
        "Are you sure you want to shut down the application?",
        confirm_payload=confirm_payload,
        cancel_payload=cancel_payload,
    )
    if confirmed:
        return await ctx.app.close()


@dev.command()
@lightbulb.command("pg_dump", "Back up the database.", aliases=["dbbackup", "backup"])
@lightbulb.implements(lightbulb.PrefixCommand)
async def backup_db_cmd(ctx: SnedPrefixContext) -> None:
    await ctx.app.backup_db()
    await ctx.event.message.add_reaction("✅")
    await ctx.respond("📤 Database backup complete.")


@dev.command()
@lightbulb.option("--ignore-errors", "Ignore all errors.", type=bool, default=False)
@lightbulb.command("pg_restore", "Restore database from attached dump file.", aliases=["restore"])
@lightbulb.implements(lightbulb.PrefixCommand)
async def restore_db(ctx: SnedPrefixContext) -> None:
    if not ctx.attachments or not ctx.attachments[0].filename.endswith(".pgdmp"):
        embed = hikari.Embed(
            title="❌ No valid attachment",
            description=f"Required dump-file attachment not found. Expected a `.pgdmp` file.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed)
        return

    await ctx.app.rest.trigger_typing(ctx.channel_id)

    path = os.path.join(ctx.app.base_dir, "db_backup", "dev_pg_restore_snapshot.pgdmp")
    with open(path, "wb") as file:
        file.write((await ctx.attachments[0].read()))
    try:
        await ctx.event.message.delete()
    except:
        pass

    # Invalidate the cache
    ctx.app.db_cache.is_ready = False
    ctx.app.db_cache.cache = {}

    # Drop all tables
    async with ctx.app.pool.acquire() as con:
        records = await con.fetch(
            """
        SELECT * FROM pg_catalog.pg_tables 
        WHERE schemaname='public'
        """
        )
        for record in records:
            await con.execute(f"""DROP TABLE IF EXISTS {record.get("tablename")} CASCADE""")

    arg = "-e" if not ctx.options["--ignore-errors"] else ""
    code = os.system(f"pg_restore {path} {arg} -n 'public' -j 4 -d {ctx.app._dsn}")

    if code != 0 and not ctx.options["--ignore-errors"]:
        embed = hikari.Embed(
            title="❌ Fatal Error",
            description=f"Failed to load database backup, database corrupted. Shutting down as a security measure...",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed)
        return await ctx.app.close()

    elif code != 0:
        await ctx.event.message.add_reaction("❌")
        embed = hikari.Embed(
            title="❌ Fatal Error",
            description=f"Failed to load database backup, database corrupted. Shutdown recommended.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed)

    else:
        await ctx.event.message.add_reaction("✅")
        await ctx.respond("📥 Restored database from backup file.")

    # Reinitialize the cache
    await ctx.app.db_cache.startup()
    # Restart scheduler
    await ctx.app.scheduler.restart()
