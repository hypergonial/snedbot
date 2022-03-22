import typing as t

import hikari
import lightbulb

import etc.constants as const
from models.bot import SnedBot
from models.context import SnedContext
from utils import helpers

annoverse = lightbulb.Plugin("Annoverse")
annoverse.default_enabled_guilds = (372128553031958529,)

QUESTIONS_CHANNEL_ID = 955463477760229397
OUTPUT_CHANNEL_ID = 955463511767654450

question_counters: t.Dict[hikari.Snowflake, int] = {}


@annoverse.command
@lightbulb.option("question", "The question you want to ask!")
@lightbulb.command("ask", "Ask a question on the roundtable!", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def ask_cmd(ctx: SnedContext, question: str) -> None:
    assert ctx.member is not None and ctx.interaction is not None

    if ctx.channel_id != QUESTIONS_CHANNEL_ID:
        if ctx.interaction.locale == "de":
            embed = hikari.Embed(
                title="❌ Ungültiger Kanal!",
                description=f"Stelle deine Frage in <#{QUESTIONS_CHANNEL_ID}>",
                color=const.ERROR_COLOR,
            )
        else:
            embed = hikari.Embed(
                title="❌ Invalid Channel!",
                description=f"You should ask your question in <#{QUESTIONS_CHANNEL_ID}>",
                color=const.ERROR_COLOR,
            )

        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    if (
        question_counters.get(ctx.author.id)
        and question_counters[ctx.author.id] >= 3
        and not helpers.includes_permissions(
            lightbulb.utils.permissions_for(ctx.member), hikari.Permissions.MANAGE_MESSAGES
        )
    ):
        if ctx.interaction.locale == "de":
            embed = hikari.Embed(
                title="❌ zu viele Fragen! :)",
                description="Sorry, du kannst leider nur bis zu drei Fragen stellen!",
                color=const.ERROR_COLOR,
            )
        else:
            embed = hikari.Embed(
                title="❌ Asking too much! :)",
                description="Sorry, you can only ask up to three questions!",
                color=const.ERROR_COLOR,
            )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    await ctx.app.rest.create_message(OUTPUT_CHANNEL_ID, f"{ctx.member.mention} **asks:** {question[:500]}")
    if not question_counters.get(ctx.author.id):
        question_counters[ctx.author.id] = 0
    question_counters[ctx.author.id] += 1

    if ctx.interaction.locale == "de":
        embed = hikari.Embed(
            title="✅ Frage eingereicht!",
            description="Andere können ihre Fragen über `/ask` stellen!",
            color=const.EMBED_GREEN,
        )
    else:
        embed = hikari.Embed(
            title="✅ Question submitted!",
            description="Others can submit their question by using `/ask`!",
            color=const.EMBED_GREEN,
        )
    await ctx.respond(embed=embed)


def load(bot: SnedBot) -> None:
    bot.add_plugin(annoverse)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(annoverse)
