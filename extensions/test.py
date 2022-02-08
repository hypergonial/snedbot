import asyncio
import logging

import hikari
import lightbulb
import miru
from miru.ext import nav
from models.bot import SnedBot
from utils import helpers
import perspective

logger = logging.getLogger(__name__)

test = lightbulb.Plugin("Test")


@test.command()
@lightbulb.option("text", "Text to analyze.")
@lightbulb.command("testmultiple", "aaa", auto_defer=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def testmultiple_cmd(ctx: lightbulb.SlashContext) -> None:
    text = ctx.options.text
    attribs = perspective.Attribute(perspective.AttributeName.TOXICITY)
    resps = []
    for i in range(1, 80):
        try:
            print(f"REQUEST {i}")
            resp: perspective.AnalysisResponse = await ctx.app.perspective.analyze(text, ["en"], [attribs])
            resps.append(resp)
        except:
            raise

    resp_strs = []
    for resp in resps:
        score = resp.attribute_scores[0].summary
        resp_strs.append(f"{score.value}")
    await ctx.respond("\n".join(resp_strs))


@test.command()
@lightbulb.option("text", "Text to analyze.")
@lightbulb.command("test", "aaa", auto_defer=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def test_cmd(ctx: lightbulb.SlashContext) -> None:
    text = ctx.options.text
    attribs = [
        perspective.Attribute(perspective.AttributeName.TOXICITY),
        perspective.Attribute(perspective.AttributeName.SEVERE_TOXICITY),
        perspective.Attribute(perspective.AttributeName.IDENTITY_ATTACK),
        perspective.Attribute(perspective.AttributeName.PROFANITY),
        perspective.Attribute(perspective.AttributeName.INSULT),
        perspective.Attribute(perspective.AttributeName.THREAT),
    ]

    resp: perspective.AnalysisResponse = await ctx.app.perspective.analyze(text, ["en"], attribs)

    content = "```"
    for score in resp.attribute_scores:
        content = f"{content}\n{score.name}: {score.summary.score_type}: {score.summary.value}"
    content = f"{content}```"
    await ctx.respond(content=content)


def load(bot: SnedBot) -> None:
    bot.add_plugin(test)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(test)
