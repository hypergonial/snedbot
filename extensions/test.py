import logging

import hikari
import lightbulb
import miru

logger = logging.getLogger(__name__)

test = lightbulb.Plugin("Test")


def load(bot):
    logging.info("Adding plugin: Test")
    bot.add_plugin(test)


def unload(bot):
    logging.info("Removing plugin: Test")
    bot.remove_plugin(test)
