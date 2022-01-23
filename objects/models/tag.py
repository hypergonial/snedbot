from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Tag:
    """
    Represents a tag object.
    """

    guild_id: int
    name: str
    owner_id: int
    aliases: Optional[List[str]]
    content: str
