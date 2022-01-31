from typing import List

from objects.models.errors import TagAlreadyExists, TagNotFound
from objects.models.tag import Tag


class TagHandler:
    """
    A class for common database operations regarding tags
    """

    def __init__(self, bot):
        self.bot = bot

    async def get(self, name: str, guild_id: int) -> Tag:
        """
        Returns a Tag object for the given name & guild ID, returns None if not found.
        Will try to find aliases too.
        """
        async with self.bot.pool.acquire() as con:
            result = await self.bot.pool.fetch(
                """SELECT * FROM tags WHERE tag_name = $1 AND guild_id = $2""",
                name.lower(),
                guild_id,
            )
            if len(result) != 0:
                tag = Tag(
                    guild_id=result[0].get("guild_id"),
                    name=result[0].get("tag_name"),
                    owner_id=result[0].get("tag_owner_id"),
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
                    guild_id=result[0].get("guild_id"),
                    name=result[0].get("tag_name"),
                    owner_id=result[0].get("tag_owner_id"),
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

    async def get_all(self, guild_id: int) -> List[Tag]:
        """
        Returns a list of all tags for the specified guild.
        """
        results = await self.bot.pool.fetch("""SELECT * FROM tags WHERE guild_id = $1""", guild_id)
        if len(results) != 0:
            tags = []
            for result in results:
                tag = Tag(
                    guild_id=result.get("guild_id"),
                    name=result.get("tag_name"),
                    owner_id=result.get("tag_owner_id"),
                    aliases=result.get("tag_aliases"),
                    content=result.get("tag_content"),
                )
                tags.append(tag)
            return tags

    async def delete(self, name: str, guild_id: int):
        await self.bot.pool.execute(
            """DELETE FROM tags WHERE tag_name = $1 AND guild_id = $2""",
            name,
            guild_id,
        )

    async def migrate(self, origin_id: int, destination_id: int, invoker_id: int, name: str) -> None:
        """
        Migrates a tag from one guild to another.
        """
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

    async def migrate_all(self, origin_id: int, destination_id: int, invoker_id: int, strategy: str) -> None:
        """
        Migrates all tags from one server to a different one. 'strategy' defines overriding behaviour.

        override - Override all tags in the destination server.
        keep - Keep conflicting tags in the destination server.

        Note: Migration of all tags does not migrate aliases.
        """
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

        if strategy == "override":
            async with self.bot.pool.acquire() as con:
                await con.executemany(
                    """
                INSERT INTO tags (guild_id, tag_name, tag_owner_id, tag_aliases, tag_content)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (guild_id, tag_name) DO
                UPDATE SET owner_id=$3, aliases=$4, content = $5""",
                    tags_unpacked,
                )
        elif strategy == "keep":
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
