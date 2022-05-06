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


# Copyright (C) 2022-present HyperGH

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see: https://www.gnu.org/licenses
