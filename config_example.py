import typing as t

import attr

"""
Configuration file example for the Discord bot Sned.
The actual configuration is read from 'config.py', which must exist.
All secrets are stored and read from the .env file.
"""


@attr.frozen(weakref_slot=False)
class Config:
    DEV_MODE: bool = False  # Control debugging mode, commands will default to DEBUG_GUILDS if True

    ERROR_LOGGING_CHANNEL: int = 123456789  # Error tracebacks will be sent here if specified

    DB_BACKUP_CHANNEL: int = 123456789  # DB backups will be sent here if specified

    DEBUG_GUILDS: t.Sequence[int] = (123, 456, 789)  # Commands will only be registered here if DEV_MODE is on


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
