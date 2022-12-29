import asyncio
import logging
import os
import pathlib
import typing as t

import aiohttp
import hikari
import kosu
import lightbulb
import miru

import utils.db_backup as db_backup
from config import Config
from models.db import Database
from models.errors import UserBlacklistedError
from models.mod_actions import ModActions
from utils import cache, helpers, scheduler
from utils.tasks import IntervalLoop

from .context import *


async def is_not_blacklisted(ctx: SnedContext) -> bool:
    """Evaluate if the user is blacklisted or not.

    Parameters
    ----------
    ctx : SnedContext
        The context to evaluate under.

    Returns
    -------
    bool
        A boolean determining if the user is blacklisted or not.

    Raises
    ------
    UserBlacklistedError
        The user is blacklisted.
    """
    records = await ctx.app.db_cache.get(table="blacklist", user_id=ctx.user.id)

    if not records:
        return True

    raise UserBlacklistedError("User is blacklisted from using the application.")


class SnedBot(lightbulb.BotApp):
    """A customized subclass of lightbulb.BotApp

    Parameters
    ----------
    config : Config
        The bot configuration to initialize the bot with.
        See the included config_example.py for formatting help.
    """

    def __init__(self, config: Config) -> None:
        self._started = asyncio.Event()
        self._is_started = False

        cache_settings = hikari.impl.CacheSettings(
            components=hikari.api.CacheComponents.ALL, max_messages=100000, max_dm_channel_ids=50
        )
        intents = (
            hikari.Intents.GUILDS
            | hikari.Intents.GUILD_MEMBERS
            | hikari.Intents.GUILD_BANS
            | hikari.Intents.GUILD_EMOJIS
            | hikari.Intents.GUILD_INVITES
            | hikari.Intents.ALL_MESSAGE_REACTIONS
            | hikari.Intents.ALL_MESSAGES
            | hikari.Intents.MESSAGE_CONTENT
        )

        self.dev_mode: bool = config.DEV_MODE

        default_enabled_guilds = (config.DEBUG_GUILDS or ()) if self.dev_mode else ()

        token = os.getenv("TOKEN")

        if not token:
            raise RuntimeError("TOKEN not found in environment.")

        super().__init__(
            token=token,
            cache_settings=cache_settings,
            default_enabled_guilds=default_enabled_guilds,
            intents=intents,
            owner_ids=(163979124820541440,),
            prefix="dev",
            help_class=None,
            banner=None,
        )

        # Initizaling configuration and database
        self._config = config
        self._db = Database(self)
        self._session: t.Optional[aiohttp.ClientSession] = None
        self._db_cache = cache.DatabaseCache(self)
        self._mod = ModActions(self)
        miru.install(self)

        # Some global variables
        self._base_dir = str(pathlib.Path(os.path.abspath(__file__)).parents[1])
        self._db_backup_loop = IntervalLoop(self.backup_db, seconds=3600 * 24)
        self.skip_first_db_backup = True  # Set to False to backup DB on bot startup too
        self._user_id: t.Optional[hikari.Snowflake] = None
        self._perspective: t.Optional[kosu.Client] = None
        self._scheduler = scheduler.Scheduler(self)
        self._initial_guilds: t.List[hikari.Snowflake] = []

        self.check(is_not_blacklisted)

        self.start_listeners()

    @property
    def user_id(self) -> hikari.Snowflake:
        """The application user's ID."""
        if self._user_id is None:
            raise hikari.ComponentStateConflictError("The bot is not yet initialized, user_id is unavailable.")

        return self._user_id

    @property
    def is_ready(self) -> bool:
        """Indicates if the application is ready to accept instructions or not.
        Alias for BotApp.is_alive"""
        return self.is_alive

    @property
    def base_dir(self) -> str:
        """The absolute path to the bot's project."""
        return self._base_dir

    @property
    def session(self) -> aiohttp.ClientSession:
        """The aiohttp client session used by the bot."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    @property
    def db(self) -> Database:
        """The main database connection pool of the bot."""
        return self._db

    @property
    def db_cache(self) -> cache.DatabaseCache:
        """The database cache instance of the bot."""
        return self._db_cache

    @property
    def scheduler(self) -> scheduler.Scheduler:
        """The scheduler instance of the bot."""
        return self._scheduler

    @property
    def perspective(self) -> kosu.Client:
        """The perspective client of the bot."""
        if self._perspective is None:
            raise hikari.ComponentStateConflictError(
                "The bot is not initialized or no perspective API key was found in the environment."
            )
        return self._perspective

    @property
    def config(self) -> Config:
        """The passed configuration object."""
        return self._config

    @property
    def mod(self) -> ModActions:
        """The moderation actions instance of the bot. Handles moderation of users and contains useful methods for such purposes."""
        return self._mod

    @property
    def is_started(self) -> bool:
        """Boolean indicating if the bot has started up or not."""
        return self._is_started

    def start_listeners(self) -> None:
        """
        Start all listeners located in this class.
        """
        self.subscribe(hikari.StartingEvent, self.on_starting)
        self.subscribe(hikari.StartedEvent, self.on_started)
        self.subscribe(hikari.GuildAvailableEvent, self.on_guild_available)
        self.subscribe(lightbulb.LightbulbStartedEvent, self.on_lightbulb_started)
        self.subscribe(hikari.MessageCreateEvent, self.on_message)
        self.subscribe(hikari.StoppingEvent, self.on_stopping)
        self.subscribe(hikari.StoppedEvent, self.on_stop)
        self.subscribe(hikari.GuildJoinEvent, self.on_guild_join)
        self.subscribe(hikari.GuildLeaveEvent, self.on_guild_leave)

    async def wait_until_started(self) -> None:
        """
        Wait until the bot has started up
        """
        await asyncio.wait_for(self._started.wait(), timeout=None)

    async def get_slash_context(
        self,
        event: hikari.InteractionCreateEvent,
        command: lightbulb.SlashCommand,
        cls: t.Type[lightbulb.SlashContext] = SnedSlashContext,
    ) -> SnedSlashContext:
        return await super().get_slash_context(event, command, cls)  # type: ignore

    async def get_user_context(
        self,
        event: hikari.InteractionCreateEvent,
        command: lightbulb.UserCommand,
        cls: t.Type[lightbulb.UserContext] = SnedUserContext,
    ) -> SnedUserContext:
        return await super().get_user_context(event, command, cls)  # type: ignore

    async def get_message_context(
        self,
        event: hikari.InteractionCreateEvent,
        command: lightbulb.MessageCommand,
        cls: t.Type[lightbulb.MessageContext] = SnedMessageContext,
    ) -> SnedMessageContext:
        return await super().get_message_context(event, command, cls)  # type: ignore

    async def get_prefix_context(
        self, event: hikari.MessageCreateEvent, cls: t.Type[lightbulb.PrefixContext] = SnedPrefixContext
    ) -> t.Optional[SnedPrefixContext]:
        return await super().get_prefix_context(event, cls)  # type: ignore

    async def on_guild_available(self, event: hikari.GuildAvailableEvent) -> None:
        if self.is_started:
            return
        self._initial_guilds.append(event.guild_id)

    async def on_starting(self, event: hikari.StartingEvent) -> None:
        # Connect to the database, update schema, apply pending migrations
        await self.db.connect()
        await self.db.update_schema()
        # Start scheduler, DB cache
        await self.db_cache.start()
        self.scheduler.start()

        if perspective_api_key := os.getenv("PERSPECTIVE_API_KEY"):
            self._perspective = kosu.Client(perspective_api_key, do_not_store=True)

        # Load all extensions
        self.load_extensions_from(os.path.join(self.base_dir, "extensions"), must_exist=True)

    async def on_started(self, event: hikari.StartedEvent) -> None:

        self._db_backup_loop.start()

        user = self.get_me()
        self._user_id = user.id if user else None

        logging.info(f"Startup complete, initialized as {user}.")
        activity = hikari.Activity(name="@Sned", type=hikari.ActivityType.LISTENING)
        await self.update_presence(activity=activity)

        if self.dev_mode:
            logging.warning("Developer mode is enabled!")

    async def on_lightbulb_started(self, event: lightbulb.LightbulbStartedEvent) -> None:

        # Insert all guilds the bot is member of into the db global config on startup
        async with self.db.acquire() as con:
            for guild_id in self._initial_guilds:
                await con.execute(
                    """
                    INSERT INTO global_config (guild_id) VALUES ($1)
                    ON CONFLICT (guild_id) DO NOTHING""",
                    guild_id,
                )
            logging.info(f"Connected to {len(self._initial_guilds)} guilds.")
            self._initial_guilds = []

        # Set this here so all guild_ids are in DB
        self._started.set()
        self._is_started = True
        self.unsubscribe(hikari.GuildAvailableEvent, self.on_guild_available)

    async def on_stopping(self, event: hikari.StoppingEvent) -> None:
        logging.info("Bot is shutting down...")
        self.scheduler.stop()

    async def on_stop(self, event: hikari.StoppedEvent) -> None:
        await self.db.close()
        logging.info("Closed database connection.")

    async def on_message(self, event: hikari.MessageCreateEvent) -> None:
        if not event.content:
            return

        if self.is_ready and self.db_cache.is_ready and event.is_human:
            mentions = [f"<@{self.user_id}>", f"<@!{self.user_id}>"]

            if event.content in mentions:
                user = self.get_me()
                await event.message.respond(
                    embed=hikari.Embed(
                        title="Beep Boop!",
                        description="Use `/` to access my commands and see what I can do!",
                        color=0xFEC01D,
                    ).set_thumbnail(user.avatar_url if user else None)
                )
                return

    async def on_guild_join(self, event: hikari.GuildJoinEvent) -> None:
        """Guild join behaviour"""
        await self.db.execute(
            "INSERT INTO global_config (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING", event.guild_id
        )

        if event.guild.system_channel_id is None:
            return

        me = event.guild.get_my_member()
        channel = event.guild.get_channel(event.guild.system_channel_id)

        assert me is not None
        assert isinstance(channel, hikari.TextableGuildChannel)

        if not channel or not (hikari.Permissions.SEND_MESSAGES & lightbulb.utils.permissions_in(channel, me)):
            return

        try:
            await channel.send(
                embed=hikari.Embed(
                    title="Beep Boop!",
                    description="""I have been summoned to this server. Type `/` to see what I can do!\n\nIf you have `Manage Server` permissions, you may configure the bot via `/settings`!""",
                    color=0xFEC01D,
                ).set_thumbnail(me.avatar_url)
            )
        except hikari.ForbiddenError:
            pass
        logging.info(f"Bot has been added to new guild: {event.guild.name} ({event.guild_id}).")

    async def on_guild_leave(self, event: hikari.GuildLeaveEvent) -> None:
        """Guild removal behaviour"""
        await self.db.wipe_guild(event.guild_id, keep_record=False)
        logging.info(f"Bot has been removed from guild {event.guild_id}, correlating data erased.")

    async def backup_db(self) -> None:
        if self.skip_first_db_backup:
            logging.info("Skipping database backup for this day...")
            self.skip_first_db_backup = False
            return

        file = await db_backup.backup_database()
        await self.wait_until_started()

        if self.config.DB_BACKUP_CHANNEL:
            await self.rest.create_message(
                self.config.DB_BACKUP_CHANNEL,
                f"Database Backup: {helpers.format_dt(helpers.utcnow())}",
                attachment=file,
            )
            return logging.info("Database backup complete, database backed up to specified Discord channel.")

        logging.info("Database backup complete.")


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
