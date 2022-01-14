#!/usr/bin/python3

import logging

import hikari
import lightbulb
import os

from config import config
from objects.models.bot import SnedBot

try:
    from config import config
except ImportError:
    logging.fatal(
        "Failed loading configuration. Please make sure 'config.py' exists in the root directory of the project and contains valid data."
    )
    exit()

if os.name != "nt":  # Lol imagine using Windows
    try:
        import uvloop
    except ImportError:
        logging.warn("Failed to import uvloop! Make sure to install it for enhanced performance!")
    else:
        uvloop.install()

bot = SnedBot(config)

if __name__ == "__main__":
    bot.run()
