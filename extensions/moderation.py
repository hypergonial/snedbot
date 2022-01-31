import asyncio
import logging
from typing import Dict, Union, Optional
import functools

import hikari
import lightbulb
import miru
from models import PunishFailed
from models.bot import SnedBot
from utils import helpers

logger = logging.getLogger(__name__)

mod = lightbulb.Plugin("Moderation", include_datastore=True)
mod.d.actions = {}


default_mod_settings = {
    "dm_users_on_punish": True,
    "clean_up_mod_commands": False,
}


async def get_settings(self, guild_id: int) -> Dict[str, bool]:
    records = await mod.app.db_cache.get(table="mod_config", guild_id=guild_id)
    if records:
        mod_settings = {
            "dm_users_on_punish": records[0]["dm_users_on_punish"],
            "clean_up_mod_commands": records[0]["clean_up_mod_commands"],
        }
    else:
        mod_settings = default_mod_settings

    return mod_settings


def mod_punish(func):
    """
    Decorates commands that are supposed to punish a user.
    """

    @functools.wraps(func)
    async def inner(*args, **kwargs):
        ctx: lightbulb.SlashContext = args[0]
        user: Union[hikari.User, hikari.Member] = ctx.options.user if hasattr(ctx.options, "user") else None
        reason = ctx.options.reason if hasattr(ctx.options, "reason") else None
        helpers.format_reason(reason, ctx.member, max_length=1500)

        if ctx.member.id == user.id:
            embed = hikari.Embed(
                title="❌ You cannot {pwn} yourself".format(pwn=ctx.command.name),
                description="You cannot {pwn} your own account.".format(pwn=ctx.command.name),
                color=ctx.app.error_color,
            )
            await ctx.respond(embed=embed)
            return

        if user.id == 163979124820541440:
            embed = hikari.Embed(
                title="❌ Stop hurting him!!",
                description="I swear he did nothing wrong!",
                color=ctx.app.error_color,
            )
            await ctx.respond(embed=embed)
            return

        if user.is_bot:
            embed = hikari.Embed(
                title="❌ Cannot execute on bots",
                description="This command cannot be executed on bots.",
                color=ctx.app.error_color,
            )
            await ctx.respond(embed=embed)
            return

        settings = await get_settings(ctx.guild_id)
        types_conj = {
            "warn": "warned in",
            "timeout": "timed out in",
            "kick": "kicked from",
            "ban": "banned from",
            "softban": "soft-banned from",
            "tempban": "temp-banned from",
        }

        if settings["dm_users_on_punish"] == True and isinstance(user, hikari.Member):
            guild = ctx.get_guild()
            guild_name = guild.name if guild else "Unknown server"
            embed = hikari.Embed(
                title=f"❗ You have been {types_conj[ctx.command.name]} **{guild_name}**",
                description=f"You have been {types_conj[ctx.command.name]} **{guild_name}**.\n**Reason:** ```{reason}```",
                color=ctx.app.error_color,
            )
            try:
                await user.send(embed=embed)
            except (hikari.ForbiddenError, hikari.HTTPError):
                pass

        try:
            await func(*args, **kwargs)
        except PunishFailed:
            return
        else:
            pass  # After punish actions

    return inner


async def warn(member: hikari.Member, moderator: hikari.Member, reason: Optional[str] = None) -> hikari.Embed:

    db_user = await mod.app.global_config.get_user(member.id, member.guild_id)
    db_user.warns += 1
    await mod.app.global_config.update_user(db_user)
    reason = helpers.format_reason(reason, max_length=1000)

    embed = hikari.Embed(
        title="⚠️ Warning issued",
        description=f"**{member}** has been warned by **{moderator}**.\n**Reason:** ```{reason}```",
        color=mod.app.warn_color,
    )
    log_embed = hikari.Embed(
        title="⚠️ Warning issued",
        description=f"**{member}** has been warned by **{moderator}**.\n**Warns:** {db_user.warns}\n**Reason:** ```{reason}```",
        color=mod.app.warn_color,
    )

    # TODO: Log log_embed as warn
    pass
    # TODO: Add note


@mod.command()
@lightbulb.command("test", "aaa")
@lightbulb.implements(lightbulb.SlashCommand)
async def test_cmd(ctx: lightbulb.SlashContext) -> None:
    pass


def load(bot: SnedBot) -> None:
    logging.info("Adding plugin: Test")
    bot.add_plugin(mod)


def unload(bot: SnedBot) -> None:
    logging.info("Removing plugin: Test")
    bot.remove_plugin(mod)
