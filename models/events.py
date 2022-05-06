from __future__ import annotations

import typing as t

import attr
import hikari

from models.timer import Timer

if t.TYPE_CHECKING:
    from models.bot import SnedBot
    from models.rolebutton import RoleButton


class SnedEvent(hikari.Event):
    """
    Base event for any custom event implemented by this application.
    """

    ...


class SnedGuildEvent(SnedEvent):
    """
    Base event for any custom event that occurs within the context of a guild.
    """

    app: SnedBot
    _guild_id: hikari.Snowflakeish

    @property
    def guild_id(self) -> hikari.Snowflake:
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

    def get_guild(self) -> t.Optional[hikari.GatewayGuild]:
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
    """
    Dispatched when a scheduled timer has expired.
    """

    app: SnedBot
    timer: Timer
    _guild_id: hikari.Snowflakeish


@attr.define()
class MassBanEvent(SnedGuildEvent):
    """
    Dispatched when a massban occurs.
    """

    app: SnedBot
    _guild_id: hikari.Snowflakeish
    moderator: hikari.Member
    total: int
    successful: int
    users_file: hikari.Resourceish
    reason: t.Optional[str] = None


@attr.define()
class WarnEvent(SnedGuildEvent):
    """
    Base class for all warning events.
    """

    app: SnedBot
    _guild_id: hikari.Snowflakeish
    member: hikari.Member
    moderator: hikari.Member
    warn_count: int
    reason: t.Optional[str] = None


@attr.define()
class WarnCreateEvent(WarnEvent):
    """
    Dispatched when a user is warned.
    """

    ...


@attr.define()
class WarnRemoveEvent(WarnEvent):
    """
    Dispatched when a warning is removed from a user.
    """

    ...


@attr.define()
class WarnsClearEvent(WarnEvent):
    """
    Dispatched when warnings are cleared for a user.
    """

    ...


@attr.define()
class AutoModMessageFlagEvent(SnedGuildEvent):
    """
    Dispatched when a message is flagged by auto-mod.
    """

    app: SnedBot
    message: hikari.PartialMessage
    user: hikari.PartialUser
    _guild_id: hikari.Snowflakeish
    reason: t.Optional[str] = None


@attr.define()
class RoleButtonEvent(SnedGuildEvent):
    """
    Base class for all rolebutton-related events.
    """

    app: SnedBot
    _guild_id: hikari.Snowflakeish
    rolebutton: RoleButton
    moderator: t.Optional[hikari.PartialUser] = None


@attr.define()
class RoleButtonCreateEvent(RoleButtonEvent):
    """
    Dispatched when a new rolebutton is created.
    """

    ...


@attr.define()
class RoleButtonDeleteEvent(RoleButtonEvent):
    """
    Dispatched when a rolebutton is deleted.
    """

    ...


@attr.define()
class RoleButtonUpdateEvent(RoleButtonEvent):
    """
    Dispatched when a rolebutton is updated.
    """

    ...


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
