#!/usr/bin/python3

import logging
import os

from config import config
from models import SnedBot

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
        logging.warn(
            "Failed to import uvloop! Make sure to install it via 'pip install uvloop' for enhanced performance!"
        )
    else:
        uvloop.install()

initial_extensions = [
    "extensions.error_handler",
    "extensions.userlog",
    "extensions.moderation",
    "extensions.settings",
    "extensions.reports",
    "extensions.reminders",
    "extensions.fun",
    "extensions.test",
    "extensions.tags",
    "extensions.misc",
    "extensions.role_buttons",
    "extensions.dev",
]

bot = SnedBot(config)

if __name__ == "__main__":

    for extension in initial_extensions:
        try:
            bot.load_extensions(extension)
        except Exception as error:
            logging.fatal(f"Failed loading extension {extension} due to error: {error}")
            exit()

    bot.run()
