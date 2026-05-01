from __future__ import annotations

import typing as t

import attr
import hikari

if t.TYPE_CHECKING:
    from src.models.rolebutton import RoleButton
    from src.models.timer import Timer


class SnedEvent(hikari.Event):
    """Base event for any custom event implemented by this application."""

    ...


class SnedGuildEvent(SnedEvent):
    """Base event for any custom event that occurs within the context of a guild."""

    app: hikari.RESTAware  # type: ignore
    """The currently running application."""
    _guild_id: hikari.Snowflakeish

    @property
    def guild_id(self) -> hikari.Snowflake:
        """The guild this event belongs to."""
        return hikari.Snowflake(self._guild_id)

    async def fetch_guild(self) -> hikari.RESTGuild:
        """Perform an API call to get the guild that this event relates to.

        Returns
        -------
        hikari.guilds.RESTGuild
            The guild this event occurred in.
        """
        return await self.app.rest.fetch_guild(self.guild_id)

    async def fetch_guild_preview(self) -> hikari.GuildPreview:
        """Perform an API call to get the preview of the event's guild.

        Returns
        -------
        hikari.guilds.GuildPreview
            The preview of the guild this event occurred in.
        """
        return await self.app.rest.fetch_guild_preview(self.guild_id)

    def get_guild(self) -> hikari.GatewayGuild | None:
        """Get the cached guild that this event relates to, if known.

        If not known, this will return `builtins.None` instead.

        Returns
        -------
        Optional[hikari.guilds.GatewayGuild]
            The guild this event relates to, or `builtins.None` if not known.
        """
        if not isinstance(self.app, hikari.CacheAware):
            return None

        return self.app.cache.get_guild(self.guild_id)


@attr.define()
class TimerCompleteEvent(SnedGuildEvent):
    """Dispatched when a scheduled timer has expired."""

    app: hikari.RESTAware
    timer: Timer
    """The timer that was dispatched."""
    _guild_id: hikari.Snowflakeish


@attr.define()
class MassBanEvent(SnedGuildEvent):
    """Dispatched when a massban occurs."""

    app: hikari.RESTAware
    _guild_id: hikari.Snowflakeish
    moderator: hikari.Member
    """The moderator responsible for the massban."""
    total: int
    """The total number of users that were attempted to be banned."""
    successful: int
    """The actual amount of users that have been banned."""
    logfile: hikari.Resourceish
    """The massban session logfile."""
    reason: str | None = None
    """The reason for the massban."""


@attr.define()
class WarnEvent(SnedGuildEvent):
    """Base class for all warning events."""

    app: hikari.RESTAware
    _guild_id: hikari.Snowflakeish
    member: hikari.Member
    """The member that was warned."""
    moderator: hikari.Member
    """The moderator that warned the member."""
    warn_count: int
    """The amount of warnings the member has."""
    reason: str | None = None
    """The reason for the warning."""


@attr.define()
class WarnCreateEvent(WarnEvent):
    """Dispatched when a user is warned."""


@attr.define()
class WarnRemoveEvent(WarnEvent):
    """Dispatched when a warning is removed from a user."""


@attr.define()
class WarnsClearEvent(WarnEvent):
    """Dispatched when warnings are cleared for a user."""


@attr.define()
class AutoModMessageFlagEvent(SnedGuildEvent):
    """Dispatched when a message is flagged by auto-mod."""

    app: hikari.RESTAware
    message: hikari.PartialMessage
    """The message that was flagged."""
    user: hikari.PartialUser
    """The user that sent the message."""
    _guild_id: hikari.Snowflakeish
    reason: str | None = None
    """The reason for the flag."""


@attr.define()
class RoleButtonEvent(SnedGuildEvent):
    """Base class for all rolebutton-related events."""

    app: hikari.RESTAware
    _guild_id: hikari.Snowflakeish
    rolebutton: RoleButton
    """The rolebutton that was altered."""
    moderator: hikari.PartialUser | None = None
    """The moderator that altered the rolebutton."""


@attr.define()
class RoleButtonCreateEvent(RoleButtonEvent):
    """Dispatched when a new rolebutton is created."""


@attr.define()
class RoleButtonDeleteEvent(RoleButtonEvent):
    """Dispatched when a rolebutton is deleted."""


@attr.define()
class RoleButtonUpdateEvent(RoleButtonEvent):
    """Dispatched when a rolebutton is updated."""


# Copyright (C) 2022-present hypergonial

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
