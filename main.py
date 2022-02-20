#!/usr/bin/python3

import logging
import os
import platform

from models import SnedBot

if int(platform.python_version_tuple()[1]) < 10:
    logging.fatal("Python version must be 3.10 or greater! Exiting...")
    raise RuntimeError("Python version is not 3.10 or greater.")

try:
    from config import Config
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
    "extensions.command_handler",
    "extensions.userlog",
    "extensions.moderation",
    "extensions.automod",
    "extensions.settings",
    "extensions.reports",
    "extensions.starboard",
    "extensions.reminders",
    "extensions.fun",
    "extensions.test",
    "extensions.tags",
    "extensions.misc",
    "extensions.role_buttons",
    "extensions.troubleshooter",
    "extensions.dev",
]

bot = SnedBot(Config())

if __name__ == "__main__":

    for extension in initial_extensions:
        try:
            bot.load_extensions(extension)
        except Exception as error:
            logging.fatal(f"Failed loading extension {extension} due to error: {error}")
            exit()

    bot.run()
