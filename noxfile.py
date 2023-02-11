import os

import nox
from nox import options

PATH_TO_PROJECT = os.path.join(".")
SCRIPT_PATHS = [
    PATH_TO_PROJECT,
    "noxfile.py",
]

options.sessions = ["format_fix"]


@nox.session()
def format_fix(session: nox.Session):
    session.install("black")
    session.install("ruff")
    session.run("python", "-m", "black", *SCRIPT_PATHS)
    session.run("python", "-m", "ruff", *SCRIPT_PATHS, "--fix")


@nox.session()
def format(session: nox.Session):
    session.install("-U", "black")
    session.install("-U", "ruff")
    session.run("python", "-m", "black", *SCRIPT_PATHS, "--check")
    session.run("python", "-m", "ruff", *SCRIPT_PATHS)


# Copyright (C) 2022-present HyperGH

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
