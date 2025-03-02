import ast
import contextlib
import logging
import os
import shlex
import subprocess
import textwrap
import traceback
import typing as t

import arc
import hikari
import miru
from miru.ext import nav

from config import Config
from src.etc import const
from src.models import AuthorOnlyNavigator
from src.models.client import SnedClient, SnedContext, SnedPlugin
from src.models.views import AuthorOnlyView

logger = logging.getLogger(__name__)

plugin = SnedPlugin(
    "Development", default_enabled_guilds=Config().DEBUG_GUILDS, default_permissions=hikari.Permissions.ADMINISTRATOR
).add_hook(arc.owner_only)


class CodeInputModal(miru.Modal):
    code = miru.TextInput(label="Code", placeholder="Enter Python code here", custom_id="code", required=True)


class TrashButton(nav.NavButton):
    def __init__(self):
        super().__init__(style=hikari.ButtonStyle.SECONDARY, emoji="🗑️", row=1)

    async def callback(self, ctx: miru.ViewContext) -> None:
        assert self.view.message is not None
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
    async def trash(self, ctx: miru.ViewContext, button: miru.Button) -> None:
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
    ctx: SnedContext,
    messageable: hikari.SnowflakeishOr[hikari.TextableChannel | hikari.User],
    text: str,
    *,
    prefix: str = "",
    suffix: str = "",
) -> None:
    """Send command output paginated if appropriate."""
    text = str(text)
    channel_id = None
    if not isinstance(messageable, hikari.User):
        channel_id = hikari.Snowflake(messageable)

    if len(text) <= 2000:
        if channel_id:
            view = TrashView(ctx.author, timeout=300)
            message = await ctx.client.rest.create_message(
                channel_id, f"{prefix}{format_output(text)}{suffix}", components=view
            )
            ctx.client.miru.start_view(view, bind_to=message)
        else:
            assert isinstance(messageable, (hikari.TextableChannel, hikari.User))
            await messageable.send(f"{prefix}{format_output(text)}{suffix}")
            return

    buttons: list[nav.NavItem] = [
        nav.FirstButton(emoji=const.EMOJI_FIRST),
        nav.PrevButton(emoji=const.EMOJI_PREV),
        nav.IndicatorButton(),
        nav.NextButton(emoji=const.EMOJI_NEXT),
        nav.LastButton(emoji=const.EMOJI_LAST),
        TrashButton(),
    ]
    paginator = nav.Paginator(prefix=prefix, suffix=suffix, max_len=2000)

    for line in text.split("\n"):
        paginator.add_line(format_output(line))

    navmenu = OutputNav(ctx.author, pages=list(paginator.pages), items=buttons, timeout=300)

    if not channel_id:
        assert isinstance(messageable, hikari.User)
        channel_id = hikari.Snowflake(await messageable.fetch_dm_channel())

    builder = await navmenu.build_response_async(ctx.client.miru)
    await builder.send_to_channel(channel_id)


async def run_shell(ctx: SnedContext, code: str) -> None:
    """Run code in shell and return output to Discord."""
    code = str(code).replace("```py", "").replace("`", "").strip()

    await ctx.defer()
    try:
        result = subprocess.run(shlex.split(code), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10.0)
    except subprocess.TimeoutExpired as e:
        out_bytes = e.stderr or e.stdout
        out = ":\n" + out_bytes.decode("utf-8") if out_bytes else ""

        return await send_paginated(ctx, ctx.channel_id, "Process timed out" + out, prefix="```ansi\n", suffix="```")

    if result.returncode != 0 and result.stderr and result.stderr.decode("utf-8"):
        return await send_paginated(
            ctx, ctx.channel_id, result.stderr.decode("utf-8"), prefix="```ansi\n", suffix="```"
        )

    if result.stdout and result.stdout.decode("utf-8"):
        await send_paginated(ctx, ctx.channel_id, result.stdout.decode("utf-8"), prefix="```ansi\n", suffix="```")


@plugin.include
@arc.slash_command("load", "Load an extension.")
async def load_cmd(
    ctx: SnedContext, extension_name: arc.Option[str, arc.StrParams("The name of the extension to load.")]
) -> None:
    ctx.client.load_extension(extension_name)
    await ctx.respond(f"📥 `{extension_name}`")


@plugin.include
@arc.slash_command("unload", "Unload an extension.")
async def unload_cmd(
    ctx: SnedContext, extension_name: arc.Option[str, arc.StrParams("The name of the extension to unload.")]
) -> None:
    ctx.client.unload_extension(extension_name)
    await ctx.respond(f"📤 `{extension_name}`")


@plugin.include
@arc.slash_command("py", "Run code.")
async def eval_py(ctx: SnedContext) -> None:
    globals_dict: dict[str, t.Any] = {
        "_author": ctx.author,
        "_bot": ctx.client.app,
        "_app": ctx.client.app,
        "_client": ctx.client,
        "_channel": ctx.get_channel(),
        "_guild": ctx.get_guild(),
        "_ctx": ctx,
    }

    modal = CodeInputModal()
    await ctx.respond_with_builder(modal.build_response(ctx.client.miru))
    await modal.wait()
    if modal.code.value is None:
        return

    code = modal.code.value.replace("```py", "").replace("`", "").strip()

    # Check if last line is an expression and return it if so
    abstract_syntax_tree = ast.parse(code, filename=f"{ctx.guild_id}{ctx.channel_id}.py")
    node: list[ast.stmt] = abstract_syntax_tree.body

    if node and type(node[0]) is ast.Expr:
        code_split = code.split("\n")
        code_split[-1] = f"return {code_split[-1]}"
        code = "\n".join(code_split)

    code_func = "async def _container():\n" + textwrap.indent(code, "   ")

    await ctx.defer()

    try:
        exec(code_func, globals_dict, locals())
        return_value = await locals()["_container"]()

        if return_value is not None:
            await send_paginated(ctx, ctx.channel_id, return_value, prefix="```py\n", suffix="```")

    except Exception as e:
        with contextlib.suppress(hikari.ForbiddenError):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Exception encountered",
                    description=f"```{e.__class__.__name__}: {e}```",
                    color=const.ERROR_COLOR,
                )
            )

        traceback_msg = "\n".join(traceback.format_exception(type(e), e, e.__traceback__))
        await send_paginated(ctx, ctx.author, traceback_msg, prefix="```py\n", suffix="```")


@plugin.include
@arc.slash_command("sh", "Run code.")
async def eval_sh(ctx: SnedContext) -> None:
    modal = CodeInputModal()
    await ctx.respond_with_builder(modal.build_response(ctx.client.miru))
    await modal.wait()
    if modal.code.value is None:
        return

    await run_shell(ctx, modal.code.value)


@plugin.include
@arc.slash_command("sync", "Sync application commands.")
async def resync_app_cmds(ctx: SnedContext) -> None:
    await ctx.defer()
    await ctx.client.resync_commands()
    await ctx.respond("🔃 Synced application commands.")


@plugin.include
@arc.slash_command("sql", "Execute an SQL file")
async def run_sql(
    ctx: SnedContext, file: arc.Option[hikari.Attachment, arc.AttachmentParams("The SQL file to execute")]
) -> None:
    if file.filename.endswith(".sql"):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ No valid attachment",
                description="Expected a `.sql` file.",
                color=const.ERROR_COLOR,
            )
        )
        return

    await ctx.defer()
    sql: str = (await file.read()).decode("utf-8")
    return_value = await ctx.client.db.execute(sql)
    await send_paginated(ctx, ctx.channel_id, str(return_value), prefix="```sql\n", suffix="```")


@plugin.include
@arc.slash_command("shutdown", "Shut down the bot.")
async def shutdown_cmd(ctx: SnedContext) -> None:
    confirm_payload = {"content": "⚠️ Shutting down...", "components": []}
    cancel_payload = {"content": "❌ Shutdown cancelled", "components": []}
    confirmed = await ctx.confirm(
        "Are you sure you want to shut down the application?",
        confirm_payload=confirm_payload,
        cancel_payload=cancel_payload,
    )
    if confirmed:
        return await ctx.client.app.close()
    await ctx.respond("❌ Shutdown cancelled")


@plugin.include
@arc.slash_command("backup", "Back up the database.")
async def backup_db_cmd(ctx: SnedContext) -> None:
    await ctx.client.backup_db()
    await ctx.respond("📤 Database backup complete.")


@plugin.include
@arc.slash_command("restore", "Restore database from attached dump file.")
async def restore_db(
    ctx: SnedContext,
    file: arc.Option[hikari.Attachment, arc.AttachmentParams("The pgdmp file to restore from")],
    ignore_errors: arc.Option[bool, arc.BoolParams("Ignore all errors. This is wildly unsafe to use!")] = False,
) -> None:
    if file.filename.endswith(".pgdmp"):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ No valid attachment",
                description="Expected a `.pgdmp` file.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.defer()

    if not os.path.isdir(os.path.join(ctx.client.base_dir, "src", "db", "backups")):
        os.mkdir(os.path.join(ctx.client.base_dir, "src", "db", "backups"))

    path = os.path.join(ctx.client.base_dir, "src", "db", "backups", "dev_pg_restore_snapshot.pgdmp")
    with open(path, "wb") as f:
        f.write((await file.read()))

    await ctx.client.db_cache.stop()

    # Drop all tables
    async with ctx.client.db.acquire() as con:
        records = await con.fetch(
            """
        SELECT * FROM pg_catalog.pg_tables
        WHERE schemaname='public'
        """
        )
        for record in records:
            await con.execute(f"""DROP TABLE IF EXISTS {record.get("tablename")} CASCADE""")

    arg = "-e" if not ignore_errors else ""
    code = os.system(f"pg_restore {path} {arg} -n 'public' -j 4 -d {ctx.client.db.dsn}")

    if code != 0 and not ignore_errors:
        await ctx.respond(
            "❌ **Fatal:** Failed to load database backup, database corrupted. Shutting down...",
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return await ctx.client.app.close()

    elif code != 0:
        await ctx.respond(
            "❌ **Fatal:** Failed to load database backup, database may be corrupted. Shutdown recommended.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    else:
        await ctx.client.db.update_schema()
        await ctx.client.db_cache.start()
        ctx.client.scheduler.restart()
        await ctx.respond("📥 Restored database from backup file.")


@plugin.include
@arc.slash_command("blacklist", "Commands to manage the blacklist.")
async def blacklist_cmd(
    ctx: SnedContext,
    mode: arc.Option[str, arc.StrParams("The mode of operation.", choices=["add", "del"])],
    user: arc.Option[hikari.User, arc.UserParams("The user to manage.")],
) -> None:
    if user.id == ctx.user.id:
        await ctx.respond("❌ Cannot blacklist self")
        return

    records = await ctx.client.db_cache.get(table="blacklist", user_id=user.id)

    if mode == "add":
        if records:
            await ctx.respond("❌ Already blacklisted")
            return

        await ctx.client.db.execute("""INSERT INTO blacklist (user_id) VALUES ($1)""", user.id)
        await ctx.client.db_cache.refresh(table="blacklist", user_id=user.id)
        await ctx.respond("✅ User added to blacklist")

    elif mode == "del":
        if not records:
            await ctx.respond("❌ Not blacklisted")
            return

        await ctx.client.db.execute("""DELETE FROM blacklist WHERE user_id = $1""", user.id)
        await ctx.client.db_cache.refresh(table="blacklist", user_id=user.id)
        await ctx.respond("✅ User removed from blacklist")

    else:
        await ctx.respond("❌ Invalid mode\nValid modes:`add`, `del`.")


@plugin.include
@arc.slash_command("resetsettings", "Reset all settings for the specified guild.")
async def resetsettings_cmd(
    ctx: SnedContext, guild_id: arc.Option[int, arc.IntParams("The guild_id to reset all settings for.")]
) -> None:
    guild = ctx.client.cache.get_guild(guild_id)

    if not guild:
        await ctx.respond("❌ Guild not found.")
        return

    confirmed = await ctx.confirm(
        f"Are you sure you want to wipe all settings for guild `{guild.id}`?",
        cancel_payload={"content": "❌ Cancelled", "components": []},
        confirm_payload={"content": "✅ Confirmed", "components": []},
    )

    if not confirmed:
        return await ctx.event.message.add_reaction("❌")

    await ctx.client.db.wipe_guild(guild)
    await ctx.client.db_cache.wipe(guild)

    await ctx.respond(f"✅ Wiped data for guild `{guild.id}`.")


@arc.loader
def load(client: SnedClient) -> None:
    client.add_plugin(plugin)


@arc.unloader
def unload(client: SnedClient) -> None:
    client.remove_plugin(plugin)


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
