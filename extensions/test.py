import asyncio
import logging

import hikari
import lightbulb
import miru
from models.bot import SnedBot
from utils import helpers

logger = logging.getLogger(__name__)

test = lightbulb.Plugin("Test")


@test.command()
@lightbulb.command("test", "aaa")
@lightbulb.implements(lightbulb.SlashCommand)
async def test_cmd(ctx: lightbulb.SlashContext) -> None:
    pass


def load(bot: SnedBot) -> None:
    bot.add_plugin(test)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(test)
