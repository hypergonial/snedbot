import typing as t
import attr

import hikari


@attr.define()
class Timer:
    """
    Represents a timer object.
    """

    id: int
    guild_id: hikari.Snowflake
    user_id: hikari.Snowflake
    channel_id: t.Optional[hikari.Snowflake]
    event: str
    expires: int
    notes: t.Optional[str]
