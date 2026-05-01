import os
import typing as t

import hikari


class Config:
    _instance: t.ClassVar[t.Optional[t.Self]] = None

    def __new__(cls, *args: t.Any, **kwargs: t.Any) -> t.Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(
        self,
    ) -> None:
        try:
            self.DEV_MODE = os.getenv("DEV_MODE", "False").lower() in ("true", "1", "yes")
            self.ERROR_LOGGING_CHANNEL = (
                hikari.Snowflake(os.getenv("ERROR_LOGGING_CHANNEL", "0"))
                if os.getenv("ERROR_LOGGING_CHANNEL")
                else None
            )
            self.DB_BACKUP_CHANNEL = (
                hikari.Snowflake(os.getenv("DB_BACKUP_CHANNEL", "0")) if os.getenv("DB_BACKUP_CHANNEL") else None
            )
            self.DEBUG_GUILDS: t.Sequence[hikari.Snowflake] = (
                tuple(map(hikari.Snowflake, os.getenv("DEBUG_GUILDS", "").split(",")))
                if os.getenv("DEBUG_GUILDS")
                else ()
            )
        except Exception as e:
            raise ValueError(f"Invalid configuration value: {e}")
