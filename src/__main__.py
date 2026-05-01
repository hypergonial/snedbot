#!/usr/bin/python3

import asyncio
import os
import pathlib
import platform
import re
import sys

from src.config import Config
from src.models.client import SnedClient

DOTENV_REGEX = re.compile(r"^(?P<identifier>[A-Za-z_]+[A-Za-z0-9_]*)=(?P<value>[^#]+)(#.*)?$")
BASE_DIR = str(pathlib.Path(os.path.abspath(__file__)).parents[1])

if __name__ != "__main__":
    print("This module is not meant to be imported! Exiting...", file=sys.stderr)
    exit(1)

if int(platform.python_version_tuple()[1]) < 14:
    print("Python version must be 3.14 or greater! Exiting...", file=sys.stderr)
    exit(1)

try:
    with open(os.path.join(BASE_DIR, ".env")) as env:
        for line in env.readlines():
            match = DOTENV_REGEX.match(line)
            if not match:
                continue
            if match.group("identifier") in os.environ:
                continue
            os.environ[match.group("identifier")] = match.group("value").strip()
except FileNotFoundError:
    print("'.env' file not found, using values from the environment only.", file=sys.stderr)


if os.name != "nt":  # Lol imagine using Windows
    try:
        import uvloop

        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())  # type: ignore
    except ImportError:
        print(
            "Failed to import uvloop! Make sure to install it via 'pip install uvloop' for enhanced performance!",
            file=sys.stderr,
        )


client = SnedClient(Config())
client.app.run()


# Copyright (C) 2022-present hypergonial

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see: https://www.gnu.org/licenses
