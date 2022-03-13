import typing as t

import attr
import hikari


@attr.define()
class Tag:
    """
    Represents a tag object.
    """

    guild_id: hikari.Snowflake
    name: str
    owner_id: hikari.Snowflake
    aliases: t.Optional[t.List[str]]
    content: str
    creator_id: t.Optional[hikari.Snowflake] = None
    uses: int = 0
