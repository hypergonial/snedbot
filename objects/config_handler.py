import json
import logging
from typing import List

import asyncpg

from objects.models.db_user import User
from objects.utils import tasks

logger = logging.getLogger(__name__)


class ConfigHandler:
    """
    Handles the global configuration & userdata within the database.
    These tables are created automatically as they must exist.
    """

    def __init__(self, bot):
        self.bot = bot
        loop = tasks.IntervalLoop(self.cleanup_userdata, seconds=5.0)
        loop.start()

    async def cleanup_userdata(self):
        """Clean up garbage userdata from db"""

        await self.bot.wait_until_ready()
        logger.info("Cleaning up garbage userdata...")
        await self.bot.pool.execute("DELETE FROM users WHERE flags IS NULL and warns = 0 AND notes IS NULL")

    async def deletedata(self, guild_id):
        """
        Deletes all data related to a specific guild, including but not limited to: all settings, priviliged roles, stored tags, stored multiplayer listings etc...
        Warning! This also erases any stored warnings & other moderation actions for the guild!
        """

        # The nuclear option c:
        async with self.bot.pool.acquire() as con:
            await con.execute("""DELETE FROM global_config WHERE guild_id = $1""", guild_id)
            # This one is necessary so that the list of guilds the bot is in stays accurate
            await con.execute("""INSERT INTO global_config (guild_id) VALUES ($1)""", guild_id)

        await self.bot.db_cache.wipe(guild_id)
        logger.warning(f"Config reset and cache wiped for guild {guild_id}.")

    async def update_user(self, user: User):
        """
        Takes an instance of GlobalConfig.User and tries to either update or create a new user entry if one does not exist already
        """

        try:
            user.flags = json.dumps(user.flags) if user.flags else None
            await self.bot.pool.execute(
                """
            INSERT INTO users (user_id, guild_id, flags, warns, notes) 
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id, guild_id) DO
            UPDATE SET flags = $3, warns = $4,notes = $5""",
                user.user_id,
                user.guild_id,
                user.flags,
                user.warns,
                user.notes,
            )
        except asyncpg.exceptions.ForeignKeyViolationError:
            logger.warning(
                "Trying to update a guild db_user whose guild no longer exists. This could be due to pending timers."
            )

    async def get_user(self, user_id, guild_id) -> User:
        """
        Gets an instance of GlobalConfig.User that contains basic information about the user in relation to a guild
        Returns None if not found
        """
        result = await self.bot.pool.fetch(
            """SELECT * FROM users WHERE user_id = $1 AND guild_id = $2""",
            user_id,
            guild_id,
        )
        if result:
            user = User(
                user_id=result[0].get("user_id"),
                guild_id=result[0].get("guild_id"),
                flags=json.loads(result[0].get("flags")) if result[0].get("flags") else {},
                warns=result[0].get("warns"),
                notes=result[0].get("notes"),
            )
            return user
        else:
            user = User(user_id=user_id, guild_id=guild_id)  # Generate a new db user if none exists
            await self.update_user(user)
            return user

    async def get_all_guild_users(self, guild_id) -> List[User]:
        """
        Returns all users related to a specific guild as a list of GlobalConfig.User
        Return None if no users are contained in the database
        """
        results = await self.bot.pool.fetch("""SELECT * FROM users WHERE guild_id = $1""", guild_id)
        if results:
            users = []
            for result in results:
                user = User(
                    user_id=result.get("user_id"),
                    guild_id=result.get("guild_id"),
                    flags=result.get("flags"),
                    warns=result.get("warns"),
                    notes=result.get("notes"),
                )
                users.append(user)
            return users
