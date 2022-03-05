from typing import List, Optional

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
    aliases: Optional[List[str]]
    content: str
