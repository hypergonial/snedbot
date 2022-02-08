import asyncio
import logging

import hikari
import lightbulb
import miru
from miru.ext import nav
from models.bot import SnedBot
from utils import helpers, perspective

logger = logging.getLogger(__name__)

test = lightbulb.Plugin("Test")


@test.command()
@lightbulb.option("text", "Text to analyze.")
@lightbulb.command("testmultiple", "aaa", auto_defer=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def testmultiple_cmd(ctx: lightbulb.SlashContext) -> None:
    text = ctx.options.text
    attribs = perspective.Attribute(perspective.AttributeType.TOXICITY)
    resps = []
    for i in range(1, 10):
        resp: perspective.AnalysisResponse = await ctx.app.perspective.analyze(text, ["en"], [attribs])
        resps.append(resp)

    resp_strs = []
    for resp in resps:
        score = resp.attribute_scores[0].summary
        resp_strs.append(f"{resp.attribute_scores[0].name.value}: {score.score_type}: {score.value}")
    await ctx.respond("\n".join(resp_strs))


@test.command()
@lightbulb.option("text", "Text to analyze.")
@lightbulb.command("test", "aaa", auto_defer=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def test_cmd(ctx: lightbulb.SlashContext) -> None:
    text = ctx.options.text
    attribs = [
        perspective.Attribute(perspective.AttributeType.TOXICITY),
        perspective.Attribute(perspective.AttributeType.SEVERE_TOXICITY),
        perspective.Attribute(perspective.AttributeType.IDENTITY_ATTACK),
        perspective.Attribute(perspective.AttributeType.PROFANITY),
        perspective.Attribute(perspective.AttributeType.INSULT),
        perspective.Attribute(perspective.AttributeType.THREAT),
    ]

    resp: perspective.AnalysisResponse = await ctx.app.perspective.analyze(text, ["en"], attribs)

    content = ""
    for score in resp.attribute_scores:
        content = f"{content}\n{score.name}: {score.summary.score_type}: {score.summary.value}"

    await ctx.respond(content=content)


def load(bot: SnedBot) -> None:
    bot.add_plugin(test)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(test)
