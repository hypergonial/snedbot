from dataclasses import dataclass
from typing import List


@dataclass
class Tag:
    """
    Represents a tag object.
    """

    guild_id: int
    name: str
    owner_id: int
    aliases: List[str]
    content: str
