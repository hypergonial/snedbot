from dataclasses import dataclass
from typing import Optional


@dataclass
class Timer:
    """
    Represents a timer object.
    """

    id: int
    guild_id: int
    user_id: int
    channel_id: Optional[int]
    event: str
    expires: int
    notes: Optional[str]
