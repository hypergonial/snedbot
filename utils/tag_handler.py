from __future__ import annotations
import enum

import typing as t

import hikari

from models.errors import TagAlreadyExists, TagNotFound
from models.tag import Tag

if t.TYPE_CHECKING:
    from models import SnedBot


class TagMigrationStrategy(enum.IntEnum):
    """Valid migration strategies for migrate_all"""

    KEEP = 0
    OVERRIDE = 1


class TagHandler:
    """
    A class for common database operations regarding tags
    """

    def __init__(self, bot: SnedBot):
        self.bot: SnedBot = bot

    async def get(self, name: str, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> t.Optional[Tag]:
        """
        Returns a Tag object for the given name & guild ID, returns None if not found.
        Will try to find aliases too.
        """
        guild_id = hikari.Snowflake(guild)

        async with self.bot.pool.acquire() as con:
            result = await self.bot.pool.fetch(
                """SELECT * FROM tags WHERE tag_name = $1 AND guild_id = $2""",
                name.lower(),
                guild_id,
            )
            if len(result) != 0:
                tag = Tag(
                    guild_id=hikari.Snowflake(result[0].get("guild_id")),
                    name=result[0].get("tag_name"),
                    owner_id=hikari.Snowflake(result[0].get("tag_owner_id")),
                    aliases=result[0].get("tag_aliases"),
                    content=result[0].get("tag_content"),
                )
                return tag

            result = await con.fetch(
                """SELECT * FROM tags WHERE $1 = ANY(tag_aliases) AND guild_id = $2""",
                name.lower(),
                guild_id,
            )
            if len(result) != 0:
                tag = Tag(
                    guild_id=hikari.Snowflake(result[0].get("guild_id")),
                    name=result[0].get("tag_name"),
                    owner_id=hikari.Snowflake(result[0].get("tag_owner_id")),
                    aliases=result[0].get("tag_aliases"),
                    content=result[0].get("tag_content"),
                )
                return tag

    async def create(self, tag: Tag) -> None:
        """
        Creates a new tag based on an instance of a Tag.
        """
        await self.bot.pool.execute(
            """
        INSERT INTO tags (guild_id, tag_name, tag_owner_id, tag_aliases, tag_content)
        VALUES ($1, $2, $3, $4, $5)""",
            tag.guild_id,
            tag.name,
            tag.owner_id,
            tag.aliases,
            tag.content,
        )

    async def get_all(self, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> t.List[Tag]:
        """
        Returns a list of all tags for the specified guild.
        """
        guild_id = hikari.Snowflake(guild)
        results = await self.bot.pool.fetch("""SELECT * FROM tags WHERE guild_id = $1""", guild_id)
        if len(results) != 0:
            tags = []
            for result in results:
                tag = Tag(
                    guild_id=hikari.Snowflake(result.get("guild_id")),
                    name=result.get("tag_name"),
                    owner_id=hikari.Snowflake(result.get("tag_owner_id")),
                    aliases=result.get("tag_aliases"),
                    content=result.get("tag_content"),
                )
                tags.append(tag)
            return tags

    async def delete(self, name: str, guild: hikari.SnowflakeishOr[hikari.PartialGuild]):
        """Delete a tag from the database."""
        guild_id = hikari.Snowflake(guild)
        await self.bot.pool.execute(
            """DELETE FROM tags WHERE tag_name = $1 AND guild_id = $2""",
            name,
            guild_id,
        )

    async def update(self, tag: Tag) -> None:
        """Update a tag with new data. If the tag already exists, only the aliases & content will be updated."""

        await self.bot.pool.execute(
            """INSERT INTO tags (guild_id, tag_name, tag_owner_id, tag_aliases, tag_content)
        VALUES ($1, $2, $3, $4, $5) ON CONFLICT (guild_id, tag_name) DO
        UPDATE SET tag_aliases = $4, tag_content = $5""",
            tag.guild_id,
            tag.name,
            tag.owner_id,
            tag.aliases,
            tag.content,
        )

    async def migrate(
        self,
        origin: hikari.SnowflakeishOr[hikari.PartialGuild],
        destination: hikari.SnowflakeishOr[hikari.PartialGuild],
        invoker: hikari.SnowflakeishOr[hikari.PartialUser],
        name: str,
    ) -> None:
        """
        Migrates a tag from one guild to another.
        """

        origin_id = hikari.Snowflake(origin)
        destination_id = hikari.Snowflake(destination)
        invoker_id = hikari.Snowflake(invoker)

        dest_tag = await self.get(name, destination_id)
        if not dest_tag:
            tag = await self.get(name, origin_id)
            if tag:
                tag.guild_id = destination_id  # Change it's ID so it belongs to the new guild
                tag.owner_id = invoker_id  # New owner is whoever imported the tag
                await self.create(tag)
            else:
                raise TagNotFound("This tag does not exist at origin, cannot migrate.")
        else:
            raise TagAlreadyExists("This tag already exists at destination, cannot migrate.")

    async def migrate_all(
        self,
        origin: hikari.SnowflakeishOr[hikari.PartialGuild],
        destination: hikari.SnowflakeishOr[hikari.PartialGuild],
        invoker: hikari.SnowflakeishOr[hikari.PartialUser],
        strategy: TagMigrationStrategy,
    ) -> None:
        """
        Migrates all tags from one server to a different one. 'strategy' defines overriding behaviour.

        override - Override all tags in the destination server.
        keep - Keep conflicting tags in the destination server.

        Note: Migration of all tags does not migrate aliases.
        """

        origin_id = hikari.Snowflake(origin)
        destination_id = hikari.Snowflake(destination)
        invoker_id = hikari.Snowflake(invoker)

        tags = await self.get_all(origin_id)
        tags_unpacked = []
        for tag in tags:
            """
            Unpack tag objects into a 2D list that contains all the info required about them,
            for easy insertion into the database.
            """
            tag_unpacked = [
                destination_id,
                tag.name,
                invoker_id,
                None,
                tag.content,
            ]
            tags_unpacked.append(tag_unpacked)

        if strategy == TagMigrationStrategy.OVERRIDE:
            async with self.bot.pool.acquire() as con:
                await con.executemany(
                    """
                INSERT INTO tags (guild_id, tag_name, tag_owner_id, tag_aliases, tag_content)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (guild_id, tag_name) DO
                UPDATE SET owner_id=$3, aliases=$4, content = $5""",
                    tags_unpacked,
                )
        elif strategy == TagMigrationStrategy.KEEP:
            async with self.bot.pool.acquire() as con:
                await con.executemany(
                    """
                INSERT INTO tags (guild_id, tag_name, tag_owner_id, tag_aliases, tag_content)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (guild_id, tag_name) DO
                NOTHING""",
                    tags_unpacked,
                )
        else:
            raise ValueError("Invalid strategy specified.")
