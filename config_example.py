import attr

"""
Configuration file example for the Discord bot Sned.
The actual configuration is read from 'config.py', which must exist.
"""


@attr.frozen(weakref_slot=False)
class Config:
    TOKEN: str = "oh no I leaked my token"  # Bot token

    POSTGRES_DSN: str = "postgres://postgres:my_password_here@1.2.3.4:5432/{db_name}"
    # Postgres DSN for database, must have {db_name} placeholder for database name

    IPC_SECRET: str = "oh no I leaked my IPC secret"  # Unused

    PERSPECTIVE_API_KEY: str = "oh no I leaked my Perspective API key"  # API key for Perspective

    DEV_MODE: bool = False  # Control debugging mode, commands will default to DEBUG_GUILDS if True

    ERROR_LOGGING_CHANNEL: int = 123456789  # Error tracebacks will be sent here if specified

    DB_BACKUP_CHANNEL: int = 123456789  # DB backups will be sent here if specified

    DEBUG_GUILDS: int = (123, 456, 789)  # Commands will only be registered here if DEV_MODE is on
