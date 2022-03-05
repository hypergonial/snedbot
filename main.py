#!/usr/bin/python3

import logging
import os
import platform

from models import SnedBot

if int(platform.python_version_tuple()[1]) < 10:
    logging.fatal("Python version must be 3.10 or greater! Exiting...")
    raise RuntimeError("Python version is not 3.10 or greater.")

try:
    with open(".env") as env:
        for line in env.readlines():
            if not line.strip() or line.startswith("#"):
                continue
            os.environ[line.split("=")[0]] = line.split("=")[1].split("#")[0].strip()

except FileNotFoundError:
    logging.info(".env file not found, using secrets from the environment instead.")

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

bot = SnedBot(Config())

if __name__ == "__main__":
    bot.run()
