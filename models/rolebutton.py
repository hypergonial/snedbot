from __future__ import annotations

import enum
import typing as t

import hikari
import miru

from models.db import DatabaseModel
from models.events import (
    RoleButtonCreateEvent,
    RoleButtonDeleteEvent,
    RoleButtonUpdateEvent,
)


class RoleButtonMode(enum.IntEnum):
    """The mode of operation for a role button."""

    # Add and remove roles
    TOGGLE = 0
    # Only add roles
    ADD_ONLY = 1
    # Only remove roles
    REMOVE_ONLY = 2


class RoleButton(DatabaseModel):
    def __init__(
        self,
        *,
        id: int,
        guild_id: hikari.Snowflake,
        channel_id: hikari.Snowflake,
        message_id: hikari.Snowflake,
        role_id: hikari.Snowflake,
        emoji: hikari.Emoji,
        style: hikari.ButtonStyle,
        label: t.Optional[str] = None,
        mode: RoleButtonMode = RoleButtonMode.TOGGLE,
        add_title: t.Optional[str] = None,
        add_description: t.Optional[str] = None,
        remove_title: t.Optional[str] = None,
        remove_description: t.Optional[str] = None,
    ) -> None:
        # Static
        self._id = id
        self._guild_id = guild_id
        self._channel_id = channel_id
        self._message_id = message_id
        self._custom_id = f"RB:{id}:{role_id}"
        # May be changed
        self.mode = mode
        self.emoji = emoji
        self.label = label
        self.style = style
        self.role_id = role_id
        self.add_title = add_title
        self.add_description = add_description
        self.remove_title = remove_title
        self.remove_description = remove_description

    @property
    def id(self) -> int:
        return self._id

    @property
    def guild_id(self) -> hikari.Snowflake:
        return self._guild_id

    @property
    def channel_id(self) -> hikari.Snowflake:
        return self._channel_id

    @property
    def message_id(self) -> hikari.Snowflake:
        return self._message_id

    @property
    def custom_id(self) -> str:
        return self._custom_id

    @classmethod
    async def fetch(cls, id: int) -> t.Optional[RoleButton]:
        """Fetch a rolebutton stored in the database by ID.

        Parameters
        ----------
        id : int
            The ID of the rolebutton.

        Returns
        -------
        Optional[RoleButton]
            The resolved rolebutton object, if found.
        """

        record = await cls._db.fetchrow("""SELECT * FROM button_roles WHERE entry_id = $1""", id)
        if not record:
            return None

        return cls(
            id=record.get("entry_id"),
            guild_id=hikari.Snowflake(record.get("guild_id")),
            channel_id=hikari.Snowflake(record.get("channel_id")),
            message_id=hikari.Snowflake(record.get("msg_id")),
            emoji=hikari.Emoji.parse(record.get("emoji")),
            label=record.get("label"),
            style=hikari.ButtonStyle[record.get("style")],
            mode=RoleButtonMode(record.get("mode")),
            role_id=record.get("role_id"),
            add_title=record.get("add_title"),
            add_description=record.get("add_desc"),
            remove_title=record.get("remove_title"),
            remove_description=record.get("remove_desc"),
        )

    @classmethod
    async def fetch_all(cls, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> t.List[RoleButton]:
        """Fetch all rolebuttons that belong to a given guild.

        Parameters
        ----------
        guild: SnowflakeishOr[hikari.PartialGuild]
            The guild the rolebuttons belong to.

        Returns
        -------
        List[RoleButton]
            A list of rolebuttons belonging to the specified guild.
        """

        records = await cls._db.fetch("""SELECT * FROM button_roles WHERE guild_id = $1""", hikari.Snowflake(guild))
        if not records:
            return []

        return [
            cls(
                id=record.get("entry_id"),
                guild_id=hikari.Snowflake(record.get("guild_id")),
                channel_id=hikari.Snowflake(record.get("channel_id")),
                message_id=hikari.Snowflake(record.get("msg_id")),
                emoji=hikari.Emoji.parse(record.get("emoji")),
                label=record.get("label"),
                style=hikari.ButtonStyle[record.get("style")],
                mode=RoleButtonMode(record.get("mode")),
                role_id=record.get("role_id"),
                add_title=record.get("add_title"),
                add_description=record.get("add_desc"),
                remove_title=record.get("remove_title"),
                remove_description=record.get("remove_desc"),
            )
            for record in records
        ]

    @classmethod
    async def create(
        cls,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        message: hikari.Message,
        role: hikari.SnowflakeishOr[hikari.PartialRole],
        emoji: hikari.Emoji,
        style: hikari.ButtonStyle,
        mode: RoleButtonMode,
        label: t.Optional[str] = None,
        moderator: t.Optional[hikari.PartialUser] = None,
    ) -> RoleButton:
        """Create a new rolebutton with the provided parameters.

        Parameters
        ----------
        guild : SnowflakeishOr[hikari.PartialGuild]
            The guild to create the button in.
        message : hikari.Message
            The message to attach the button to.
        role : SnowflakeishOr[hikari.PartialRole]
            The role that should be handed out by the button.
        emoji : hikari.Emoji
            The emoji that should appear on the button.
        label : Optional[str]
            The label of the button.
        style : hikari.ButtonStyle
            The style of the button.
        mode : RoleButtonMode
            The mode of operation of the button.
        moderator : Optional[hikari.PartialUser]
            The user to log the rolebutton creation under.

        Returns
        -------
        RoleButton
            The created rolebutton object.

        Raises
        ------
        hikari.ForbiddenError
            Failed to edit the provided message to add the rolebutton.
        """

        record = await cls._db.fetchrow("""SELECT entry_id FROM button_roles ORDER BY entry_id DESC""")
        id = record.get("entry_id") + 1 if record else 1
        role_id = hikari.Snowflake(role)

        button = miru.Button(
            custom_id=f"RB:{id}:{role_id}",
            emoji=emoji,
            label=label,
            style=style,
        )

        view = miru.View.from_message(message)
        view.add_item(button)
        message = await message.edit(components=view)

        await cls._db.execute(
            """
            INSERT INTO button_roles (entry_id, guild_id, channel_id, msg_id, emoji, label, style, mode, role_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            id,
            hikari.Snowflake(guild),
            message.channel_id,
            message.id,
            str(emoji),
            label,
            style.name,
            mode.value,
            hikari.Snowflake(role),
        )

        rolebutton = cls(
            id=id,
            guild_id=hikari.Snowflake(guild),
            channel_id=message.channel_id,
            message_id=message.id,
            emoji=emoji,
            label=label,
            style=style,
            mode=mode,
            role_id=hikari.Snowflake(role),
        )

        cls._app.dispatch(RoleButtonCreateEvent(cls._app, rolebutton.guild_id, rolebutton, moderator))
        return rolebutton

    async def update(self, moderator: t.Optional[hikari.PartialUser] = None) -> None:
        """Update the rolebutton with the current state of this object.

        Parameters
        ----------
        moderator : Optional[hikari.PartialUser]
            The user to log the rolebutton update under.

        Raises
        ------
        hikari.ForbiddenError
            Failed to edit or fetch the message the button belongs to.
        """

        message = await self._app.rest.fetch_message(self.channel_id, self.message_id)

        view = miru.View.from_message(message)
        buttons = [item for item in view.children if item.custom_id == self.custom_id and isinstance(item, miru.Button)]

        if not buttons:
            raise ValueError("Rolebutton not found on message.")

        button = buttons[0]

        button.emoji = self.emoji
        button.label = self.label
        button.style = self.style
        button.custom_id = f"RB:{self.id}:{self.role_id}"
        self._custom_id = button.custom_id

        message = await message.edit(components=view)

        await self._db.execute(
            """
            UPDATE button_roles SET emoji = $1, label = $2, style = $3, mode = $4, role_id = $5, add_title = $6, add_desc = $7, remove_title = $8, remove_desc = $9 WHERE entry_id = $10 AND guild_id = $11
            """,
            str(self.emoji),
            self.label,
            self.style.name,
            self.mode.value,
            self.role_id,
            self.add_title,
            self.add_description,
            self.remove_title,
            self.remove_description,
            self.id,
            self.guild_id,
        )
        self._app.dispatch(RoleButtonUpdateEvent(self._app, self.guild_id, self, moderator))

    async def delete(self, moderator: t.Optional[hikari.PartialUser] = None) -> None:
        """Delete this rolebutton, removing it from the message and the database.

        Parameters
        ----------
        moderator : Optional[hikari.PartialUser]
            The user to log the rolebutton deletion under.

        Raises
        ------
        hikari.ForbiddenError
            Failed to edit or fetch the message the button belongs to.
        """

        try:
            message = await self._app.rest.fetch_message(self.channel_id, self.message_id)
        except hikari.NotFoundError:
            pass
        else:  # Remove button if message still exists
            view = miru.View.from_message(message)

            for item in view.children:
                if item.custom_id == f"RB:{self.id}:{self.role_id}":
                    view.remove_item(item)
            message = await message.edit(components=view)

        await self._db.execute(
            """DELETE FROM button_roles WHERE guild_id = $1 AND entry_id = $2""",
            self.guild_id,
            self.id,
        )
        self._app.dispatch(RoleButtonDeleteEvent(self._app, self.guild_id, self, moderator))


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
