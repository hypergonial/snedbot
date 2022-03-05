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
