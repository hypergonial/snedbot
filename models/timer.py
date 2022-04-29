import enum
import typing as t

import attr
import hikari


class TimerEvent(enum.Enum):
    """An enum containing all types of timer events."""

    REMINDER = "reminder"
    """A timer dispatched when a reminder expires."""

    TIMEOUT_EXTEND = "timeout_extend"
    """A timer dispatched when a timeout extension needs to be applied."""

    TEMPBAN = "tempban"
    """A timer dispatched when a tempban expires."""


@attr.define()
class Timer:
    """
    Represents a timer object.
    """

    id: int
    """The ID of this timer."""

    guild_id: hikari.Snowflake
    """The guild this timer is bound to."""

    user_id: hikari.Snowflake
    """The user this timer is bound to."""

    channel_id: t.Optional[hikari.Snowflake]
    """The channel this timer is bound to."""

    event: TimerEvent
    """The event type of this timer."""

    expires: int
    """The expiry date of this timer as a UNIX timestamp."""

    notes: t.Optional[str]
    """Optional data for this timer. May be a JSON-serialized string depending on the event type."""
