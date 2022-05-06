from __future__ import annotations

import typing as t
from difflib import get_close_matches
from itertools import chain

import attr
import hikari

from models.db import DatabaseModel

if t.TYPE_CHECKING:
    from models.context import SnedContext


@attr.define()
class Tag(DatabaseModel):
    """
    Represents a tag object.
    """

    guild_id: hikari.Snowflake
    name: str
    owner_id: hikari.Snowflake
    aliases: t.Optional[t.List[str]]
    content: str
    creator_id: t.Optional[hikari.Snowflake] = None
    uses: int = 0

    @classmethod
    async def fetch(
        cls, name: str, guild: hikari.SnowflakeishOr[hikari.PartialGuild], add_use: bool = False
    ) -> t.Optional[Tag]:
        """Fetches a tag from the database.

        Parameters
        ----------
        name : str
            The name of the tag to fetch.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild the tag is located in.
        add_use : bool, optional
            If True, increments the usage counter, by default False

        Returns
        -------
        Optional[Tag]
            The tag object, if found.
        """
        guild_id = hikari.Snowflake(guild)

        if add_use:
            sql = "UPDATE tags SET uses = uses + 1 WHERE tagname = $1 AND guild_id = $2 OR $1 = ANY(aliases) AND guild_id = $2 RETURNING *"
        else:
            sql = "SELECT * FROM tags WHERE tagname = $1 AND guild_id = $2 OR $1 = ANY(aliases) AND guild_id = $2"

        record = await cls._db.fetchrow(sql, name.lower(), guild_id)

        if not record:
            return

        return cls(
            guild_id=hikari.Snowflake(record.get("guild_id")),
            name=record.get("tagname"),
            owner_id=hikari.Snowflake(record.get("owner_id")),
            creator_id=hikari.Snowflake(record.get("creator_id")) if record.get("creator_id") else None,
            aliases=record.get("aliases"),
            content=record.get("content"),
            uses=record.get("uses"),
        )

    @classmethod
    async def fetch_closest_names(
        cls, name: str, guild: hikari.SnowflakeishOr[hikari.PartialGuild]
    ) -> t.Optional[t.List[str]]:
        """Fetch the closest tagnames for the provided name.

        Parameters
        ----------
        name : str
            The name to use for finding close matches.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild the tags are located in.

        Returns
        -------
        Optional[List[str]]
            A list of tag names and aliases.
        """
        guild_id = hikari.Snowflake(guild)
        # TODO: Figure out how to fuzzymatch within arrays via SQL
        results = await cls._db.fetch("""SELECT tagname, aliases FROM tags WHERE guild_id = $1""", guild_id)

        names = [result.get("tagname") for result in results] if results else []

        if results is not None:
            names += list(chain(*[result.get("aliases") or [] for result in results]))

        return get_close_matches(name, names)

    @classmethod
    async def fetch_closest_owned_names(
        cls,
        name: str,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        owner: hikari.SnowflakeishOr[hikari.PartialUser],
    ) -> t.Optional[t.List[str]]:
        """Fetch the closest tagnames for the provided name and owner.

        Parameters
        ----------
        name : str
            The name to use for finding close matches.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild the tags are located in.
        owner : hikari.SnowflakeishOr[hikari.PartialUser]
            The owner of the tags.

        Returns
        -------
        Optional[List[str]]
            A list of tag names and aliases.
        """
        guild_id = hikari.Snowflake(guild)
        owner_id = hikari.Snowflake(owner)
        # TODO: Figure out how to fuzzymatch within arrays via SQL
        results = await cls._db.fetch(
            """SELECT tagname, aliases FROM tags WHERE guild_id = $1 AND owner_id = $2""", guild_id, owner_id
        )

        names = [result.get("tagname") for result in results] if results else []

        if results is not None:
            names += list(chain(*[result.get("aliases") or [] for result in results]))

        return get_close_matches(name, names)

    @classmethod
    async def fetch_all(
        cls,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        owner: t.Optional[hikari.SnowflakeishOr[hikari.PartialUser]] = None,
    ) -> t.List[Tag]:
        """Fetch all tags that belong to a guild, and optionally a user.

        Parameters
        ----------
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild the tags belong to.
        owner : t.Optional[hikari.SnowflakeishOr[hikari.PartialUser]], optional
            The owner the tags belong to, by default None

        Returns
        -------
        List[Tag]
            A list of tags that match the criteria.
        """
        guild_id = hikari.Snowflake(guild)
        if not owner:
            records = await cls._db.fetch("""SELECT * FROM tags WHERE guild_id = $1 ORDER BY uses DESC""", guild_id)
        else:
            records = await cls._db.fetch(
                """SELECT * FROM tags WHERE guild_id = $1 AND owner_id = $2 ORDER BY uses DESC""",
                guild_id,
                hikari.Snowflake(owner),
            )

        if not records:
            return []

        return [
            cls(
                guild_id=hikari.Snowflake(record.get("guild_id")),
                name=record.get("tagname"),
                owner_id=hikari.Snowflake(record.get("owner_id")),
                creator_id=hikari.Snowflake(record.get("creator_id")) if record.get("creator_id") else None,
                aliases=record.get("aliases"),
                content=record.get("content"),
                uses=record.get("uses"),
            )
            for record in records
        ]

    @classmethod
    async def create(
        cls,
        name: str,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        creator: hikari.SnowflakeishOr[hikari.PartialUser],
        owner: hikari.SnowflakeishOr[hikari.PartialUser],
        aliases: t.List[str],
        content: str,
    ) -> Tag:
        """Create a new tag object and save it to the database.

        Parameters
        ----------
        name : str
            The name of the tag.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild the tag belongs to.
        creator : hikari.SnowflakeishOr[hikari.PartialUser]
            The creator of the tag.
        owner : hikari.SnowflakeishOr[hikari.PartialUser]
            The current owner of the tag.
        aliases : t.List[str]
            A list of all aliases the tag has.
        content : str
            The content of the tag.

        Returns
        -------
        Tag
            The created tag object.
        """

        await cls._db.execute(
            """
            INSERT INTO tags (guild_id, tagname, creator_id, owner_id, aliases, content)
            VALUES ($1, $2, $3, $4, $5, $6)""",
            hikari.Snowflake(guild),
            name,
            hikari.Snowflake(creator),
            hikari.Snowflake(owner),
            aliases,
            content,
        )
        return cls(
            guild_id=hikari.Snowflake(guild),
            name=name,
            owner_id=hikari.Snowflake(owner),
            creator_id=hikari.Snowflake(creator),
            aliases=aliases,
            content=content,
        )

    async def delete(self) -> None:
        """Delete the tag from the database."""
        await self._db.execute("""DELETE FROM tags WHERE tagname = $1 AND guild_id = $2""", self.name, self.guild_id)

    async def update(self) -> None:
        """Update the tag's attributes and sync it up to the database."""

        await self._db.execute(
            """INSERT INTO tags (guild_id, tagname, owner_id, aliases, content)
        VALUES ($1, $2, $3, $4, $5) ON CONFLICT (guild_id, tagname) DO
        UPDATE SET owner_id = $3, aliases = $4, content = $5""",
            self.guild_id,
            self.name,
            self.owner_id,
            self.aliases,
            self.content,
        )

    def parse_content(self, ctx: SnedContext) -> str:
        """Parse a tag's contents and substitute any variables with data.

        Parameters
        ----------
        ctx : SnedContext
            The context to evaluate variables under.

        Returns
        -------
        str
            The parsed tag contents.
        """
        return self.content.replace("{user}", ctx.author.mention).replace("{channel}", f"<#{ctx.channel_id}>")


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
