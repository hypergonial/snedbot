from dataclasses import dataclass
from typing import List, Optional


@dataclass
class User:
    """
    Represents a user stored inside the database.
    """

    user_id: int
    guild_id: int
    flags: Optional[dict]
    notes: Optional[List[str]]
    warns: int = 0
