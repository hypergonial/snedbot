from __future__ import annotations

import typing as t

import hikari
import miru

from models.db import DatabaseModel


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
    ) -> None:
        # Static
        self._id = id
        self._guild_id = guild_id
        self._channel_id = channel_id
        self._message_id = message_id
        # May be changed
        self.emoji = emoji
        self.label = label
        self.style = style
        self.role_id = role_id

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
            label=record.get("buttonlabel"),
            style=hikari.ButtonStyle(record.get("buttonstyle")),
            role_id=record.get("role_id"),
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
                label=record.get("buttonlabel"),
                style=hikari.ButtonStyle(record.get("buttonstyle")),
                role_id=record.get("role_id"),
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
        label: t.Optional[str] = None,
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

        view = miru.View.from_message(message, timeout=None)
        view.add_item(button)
        message = await message.edit(components=view.build())

        await cls._db.execute(
            """
            INSERT INTO button_roles (entry_id, guild_id, channel_id, msg_id, emoji, buttonlabel, buttonstyle, role_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            id,
            hikari.Snowflake(guild),
            message.channel_id,
            message.id,
            str(emoji),
            label,
            style.name,
            hikari.Snowflake(role),
        )

        return cls(
            id=id,
            guild_id=hikari.Snowflake(guild),
            channel_id=message.channel_id,
            message_id=message.id,
            emoji=emoji,
            label=label,
            style=style,
            role_id=hikari.Snowflake(role),
        )

    async def update(self, rest: hikari.api.RESTClient) -> None:
        """Update the rolebutton with the current state of this object.

        Parameters
        ----------
        rest : hikari.api.RESTClient
            The rest client to use for API calls.

        Raises
        ------
        hikari.ForbiddenError
            Failed to edit or fetch the message the button belongs to.
        """
        button = miru.Button(
            custom_id=f"RB:{self.id}:{self.role_id}",
            emoji=self.emoji,
            label=self.label,
            style=self.style,
        )

        message = await rest.fetch_message(self.channel_id, self.message_id)

        view = miru.View.from_message(message, timeout=None)
        view.add_item(button)
        message = await message.edit(components=view.build())

        await self._db.execute(
            """
            UPDATE button_roles SET emoji = $1, buttonlabel = $2, buttonstyle = $3, role_id = $4 WHERE entry_id = $5 AND guild_id = $6
            """,
            self.emoji,
            self.label,
            self.style.name,
            self.role_id,
            self.id,
            self.guild_id,
        )

    async def delete(self, rest: hikari.api.RESTClient) -> None:
        """Delete this rolebutton, removing it from the message and the database.

        Parameters
        ----------
        rest : hikari.api.RESTClient
            The rest client to use for API calls.

        Raises
        ------
        hikari.ForbiddenError
            Failed to edit or fetch the message the button belongs to.
        """

        try:
            message = await rest.fetch_message(self.channel_id, self.message_id)
        except hikari.NotFoundError:
            pass
        else:  # Remove button if message still exists
            view = miru.View.from_message(message, timeout=None)

            for item in view.children:
                if item.custom_id == f"RB:{self.id}:{self.role_id}":
                    view.remove_item(item)
            message = await message.edit(components=view.build())

        await self._db.execute(
            """DELETE FROM button_roles WHERE guild_id = $1 AND entry_id = $2""",
            self.guild_id,
            self.id,
        )
