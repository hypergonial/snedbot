import logging
import typing as t

import hikari
import lightbulb
import miru

from etc import const
from models import SnedSlashContext
from models.bot import SnedBot
from models.context import (
    SnedApplicationContext,
    SnedContext,
    SnedMessageContext,
    SnedUserContext,
)
from models.plugin import SnedPlugin
from utils import helpers

logger = logging.getLogger(__name__)

reports = SnedPlugin("Reports")


class ReportModal(miru.Modal):
    def __init__(self, member: hikari.Member) -> None:
        super().__init__(f"Reporting {member}")
        self.add_item(
            miru.TextInput(
                label="Reason for the Report",
                placeholder="Please enter why you believe this user should be investigated...",
                style=hikari.TextInputStyle.PARAGRAPH,
                max_length=1000,
                required=True,
            )
        )
        self.add_item(
            miru.TextInput(
                label="Additional Context",
                placeholder="If you have any additional information or proof (e.g. screenshots), please link them here.",
                style=hikari.TextInputStyle.PARAGRAPH,
                max_length=1000,
            )
        )
        self.reason: t.Optional[str] = None
        self.info: t.Optional[str] = None

    async def callback(self, ctx: miru.ModalContext) -> None:
        if not ctx.values:
            return

        for item, value in ctx.values.items():
            assert isinstance(item, miru.TextInput)

            if item.label == "Reason for the Report":
                self.reason = value
            elif item.label == "Additional Context":
                self.info = value

        await ctx.defer(flags=hikari.MessageFlag.EPHEMERAL)


async def report_error(ctx: SnedContext) -> None:
    guild = ctx.get_guild()
    assert guild is not None

    await ctx.respond(
        embed=hikari.Embed(
            title="❌ Oops!",
            description=f"It looks like the moderators of **{guild.name}** did not enable this functionality.",
            color=const.ERROR_COLOR,
        ),
        flags=hikari.MessageFlag.EPHEMERAL,
    )


async def report_perms_error(ctx: SnedApplicationContext) -> None:
    await ctx.respond(
        embed=hikari.Embed(
            title="❌ Oops!",
            description=f"It looks like I do not have permissions to create a message in the reports channel. Please notify an administrator!",
            color=const.ERROR_COLOR,
        ),
        flags=hikari.MessageFlag.EPHEMERAL,
    )


async def report(
    ctx: SnedApplicationContext, member: hikari.Member, message: t.Optional[hikari.Message] = None
) -> None:

    assert ctx.member is not None and ctx.guild_id is not None

    if member.id == ctx.member.id or member.is_bot:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Huh?",
                description=f"I'm not sure how that would work...",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    records = await ctx.app.db_cache.get(table="reports", guild_id=ctx.guild_id)

    if not records or not records[0]["is_enabled"]:
        return await report_error(ctx)

    channel = ctx.app.cache.get_guild_channel(records[0]["channel_id"])
    assert isinstance(channel, hikari.TextableGuildChannel)

    if not channel:
        await ctx.app.db.execute(
            """INSERT INTO reports (is_enabled, guild_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO
            UPDATE SET is_enabled = $1""",
            False,
            ctx.guild_id,
        )
        await ctx.app.db_cache.refresh(table="reports", guild_id=ctx.guild_id)
        return await report_error(ctx)

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
    assert me is not None
    perms = lightbulb.utils.permissions_in(channel, me)

    if not (perms & hikari.Permissions.SEND_MESSAGES):
        return await report_perms_error(ctx)

    assert ctx.interaction is not None

    modal = ReportModal(member)
    await modal.send(ctx.interaction)
    await modal.wait()

    if not modal.last_context:  # Modal was closed/timed out
        return

    role_ids = records[0]["pinged_role_ids"] or []
    roles = filter(lambda r: r is not None, [ctx.app.cache.get_role(role_id) for role_id in role_ids])
    role_mentions = [role.mention for role in roles if role is not None]

    embed = hikari.Embed(
        title="⚠️ New Report",
        description=f"""
**Reporter:** {ctx.member.mention} `({ctx.member.id})`
**Reported User:**  {member.mention} `({member.id})`
**Reason:** ```{modal.reason}```
**Additional Context:** ```{modal.info or "Not provided."}```""",
        color=const.WARN_COLOR,
    )

    components = hikari.UNDEFINED

    if message:
        components = miru.View().add_item(miru.Button(label="Associated Message", url=message.make_link(ctx.guild_id)))

    await channel.send(
        " ".join(role_mentions) or hikari.UNDEFINED, embed=embed, components=components, role_mentions=True
    )

    await modal.last_context.respond(
        embed=hikari.Embed(
            title="✅ Report Submitted",
            description="A moderator will review your report shortly!",
            color=const.EMBED_GREEN,
        ),
        flags=hikari.MessageFlag.EPHEMERAL,
    )


@reports.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option("user", "The user that is to be reported.", type=hikari.Member, required=True)
@lightbulb.command("report", "Report a user to the moderation team of this server.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def report_cmd(ctx: SnedSlashContext, user: hikari.Member) -> None:
    helpers.is_member(user)
    await report(ctx, user)


@reports.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.command("Report User", "Report the targeted user to the moderation team of this server.", pass_options=True)
@lightbulb.implements(lightbulb.UserCommand)
async def report_user_cmd(ctx: SnedUserContext, target: hikari.Member) -> None:
    helpers.is_member(target)
    await report(ctx, ctx.options.target)


@reports.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.command(
    "Report Message", "Report the targeted message to the moderation team of this server.", pass_options=True
)
@lightbulb.implements(lightbulb.MessageCommand)
async def report_msg_cmd(ctx: SnedMessageContext, target: hikari.Message) -> None:
    assert ctx.guild_id is not None
    member = ctx.app.cache.get_member(ctx.guild_id, target.author)
    if not member:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Oops!",
                description="It looks like the author of this message already left the server!",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await report(ctx, member, ctx.options.target)


def load(bot: SnedBot) -> None:
    bot.add_plugin(reports)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(reports)


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
