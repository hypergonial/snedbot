import asyncio
import logging

import hikari
import lightbulb
import miru
from objects.utils import helpers

logger = logging.getLogger(__name__)

test = lightbulb.Plugin("Test")


@test.command()
@lightbulb.command("test", "aaa")
@lightbulb.implements(lightbulb.SlashCommand)
async def test_cmd(ctx: lightbulb.SlashContext) -> None:
    pass


def load(bot):
    logging.info("Adding plugin: Test")
    bot.add_plugin(test)


def unload(bot):
    logging.info("Removing plugin: Test")
    bot.remove_plugin(test)
