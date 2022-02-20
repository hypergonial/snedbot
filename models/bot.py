import asyncio
import logging
import os
import typing as t

import asyncpg
import db_backup
import hikari
import lightbulb
import miru
import perspective
from hikari.snowflakes import Snowflake
from lightbulb.ext import tasks
from utils import cache, helpers, scheduler
from utils.config_handler import ConfigHandler
from utils.tasks import IntervalLoop

from .context import *

from config import Config


async def get_prefix(bot: lightbulb.BotApp, message: hikari.Message) -> t.Union[t.List[str], str]:
    """
    Get custom prefix for guild to show prefix command deprecation warn
    """
    if message.guild_id is None:
        return "sn "

    records = await bot.db_cache.get(table="global_config", guild_id=message.guild_id)
    if records and records[0]["prefix"]:
        return records[0]["prefix"]

    return "sn "


class SnedBot(lightbulb.BotApp):
    """A customized subclass of lightbulb.BotApp

    Parameters
    ----------
    config : Dict[str, Any]
        The bot configuration to initialize the bot with.
        See the included config_example.py for formatting help.
    """

    def __init__(self, config: Config) -> None:
        self.loop = asyncio.get_event_loop()
        self._started = asyncio.Event()
        self._is_started = False

        cache_settings = hikari.CacheSettings(
            components=hikari.CacheComponents.ALL, max_messages=10000, max_dm_channel_ids=50
        )
        intents = (
            hikari.Intents.GUILDS
            | hikari.Intents.GUILD_MEMBERS
            | hikari.Intents.GUILD_BANS
            | hikari.Intents.GUILD_EMOJIS
            | hikari.Intents.GUILD_INVITES
            | hikari.Intents.ALL_MESSAGE_REACTIONS
            | hikari.Intents.ALL_MESSAGES
        )

        self.dev_mode: bool = config.DEV_MODE

        if self.dev_mode:
            default_enabled_guilds = (config.DEBUG_GUILDS) if config.DEBUG_GUILDS else ()
            db_name = "sned_exp"
        else:
            default_enabled_guilds = ()
            db_name = "sned"

        super().__init__(
            token=config.TOKEN,
            cache_settings=cache_settings,
            default_enabled_guilds=default_enabled_guilds,
            intents=intents,
            owner_ids=(163979124820541440,),
            prefix="dev",
            help_class=None,
        )

        # Initizaling configuration and database
        self._config = config
        self._dsn = self.config.POSTGRES_DSN.format(db_name=db_name)
        self._pool = self.loop.run_until_complete(asyncpg.create_pool(dsn=self._dsn))

        # Startup lightbulb.ext.tasks and miru
        tasks.load(self)
        miru.load(self)

        # Some global variables
        self._base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        self._db_backup_loop = IntervalLoop(self.backup_bot_db, hours=24.0)
        self.skip_first_db_backup = True  # Set to False to backup DB on bot startup too
        self._user_id: t.Optional[Snowflake] = None
        self._initial_guilds: t.List[Snowflake] = []

        # Color scheme
        self.error_color = 0xFF0000
        self.warn_color = 0xFFCC4D
        self.embed_blue = 0x009DFF
        self.embed_green = 0x77B255
        self.unknown_color = 0xBE1931
        self.misc_color = 0xC2C2C2

        self.start_listeners()

    @property
    def user_id(self) -> Snowflake:
        """The application user's ID."""
        if self._user_id is None:
            raise RuntimeError("The bot is not yet initialized, user_id is unavailable.")

        return self._user_id

    @property
    def is_ready(self) -> bool:
        """Indicates if the application is ready to accept instructions or not."""
        return self.is_alive

    @property
    def base_dir(self) -> str:
        """The absolute path to the bot's project."""
        return self._base_dir

    @property
    def pool(self) -> asyncpg.Pool:
        """The database connection pool of the bot."""
        if self._pool is None:
            raise RuntimeError("The bot is not initialized and has no pool.")
        return self._pool

    @property
    def config(self) -> Config:
        """The passed configuration object."""
        return self._config

    @property
    def is_started(self) -> bool:
        """Boolean indicating if the bot has started up or not."""
        return self._is_started

    def start_listeners(self) -> None:
        """
        Start all listeners located in this class.
        """
        self.subscribe(hikari.StartedEvent, self.on_startup)
        self.subscribe(hikari.GuildAvailableEvent, self.on_guild_available)
        self.subscribe(lightbulb.LightbulbStartedEvent, self.on_lightbulb_startup)
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
        return await super().get_slash_context(event, command, cls)

    async def get_user_context(
        self,
        event: hikari.InteractionCreateEvent,
        command: lightbulb.UserCommand,
        cls: t.Type[lightbulb.UserContext] = SnedUserContext,
    ) -> SnedUserContext:
        return await super().get_user_context(event, command, cls)

    async def get_message_context(
        self,
        event: hikari.InteractionCreateEvent,
        command: lightbulb.MessageCommand,
        cls: t.Type[lightbulb.MessageContext] = SnedMessageContext,
    ) -> SnedMessageContext:
        return await super().get_message_context(event, command, cls)

    async def get_prefix_context(
        self, event: hikari.MessageCreateEvent, cls: t.Type[lightbulb.PrefixContext] = SnedPrefixContext
    ) -> t.Optional[SnedPrefixContext]:
        return await super().get_prefix_context(event, cls)

    async def on_guild_available(self, event: hikari.GuildAvailableEvent) -> None:
        if self.is_started:
            return
        self._initial_guilds.append(event.guild_id)

    async def on_startup(self, event: hikari.StartedEvent) -> None:

        user = self.get_me()
        self._user_id = user.id
        self.db_cache = cache.Caching(self)
        self.global_config = ConfigHandler(self)
        self.scheduler = scheduler.Scheduler(self)
        self.perspective = perspective.Client(self.config.PERSPECTIVE_API_KEY, do_not_store=True)
        self._db_backup_loop.start()

        logging.info(f"Startup complete, initialized as {user}")
        activity = hikari.Activity(name="to @Sned", type=hikari.ActivityType.LISTENING)
        await self.update_presence(activity=activity)

        if self.dev_mode:
            logging.warning("Developer mode is enabled!")

        # Insert all guilds the bot is member of into the db global config on startup
        async with self.pool.acquire() as con:
            for guild_id in self.cache.get_guilds_view():
                await con.execute(
                    """
                INSERT INTO global_config (guild_id) VALUES ($1)
                ON CONFLICT (guild_id) DO NOTHING""",
                    guild_id,
                )

    async def on_lightbulb_startup(self, event: lightbulb.LightbulbStartedEvent) -> None:

        # Insert all guilds the bot is member of into the db global config on startup
        async with self.pool.acquire() as con:
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

    async def on_stopping(self, event: hikari.StoppingEvent) -> None:
        logging.info("Bot is shutting down...")

    async def on_stop(self, event: hikari.StoppedEvent) -> None:
        await self.pool.close()
        logging.info("Closed database connection.")

    async def on_message(self, event: hikari.MessageCreateEvent) -> None:
        if not event.content:
            return

        if self.is_ready and self.db_cache.is_ready and event.is_human:
            mentions = [f"<@{self.user_id}>", f"<@!{self.user_id}>"]

            if event.content in mentions:
                embed = hikari.Embed(
                    title="Beep Boop!",
                    description="Use `/` to access my commands and see what I can do!",
                    color=0xFEC01D,
                )
                embed.set_thumbnail(self.get_me().avatar_url)
                return await event.message.respond(embed=embed)

            elif event.content.startswith(tuple(await get_prefix(self, event.message))):
                embed = hikari.Embed(
                    title="Uh Oh!",
                    description="This bot has transitioned to slash commands, to see a list of all commands, type `/`!",
                    color=self.error_color,
                )
                embed.set_thumbnail(self.get_me().avatar_url)
                return await event.message.respond(embed=embed)

    async def on_guild_join(self, event: hikari.GuildJoinEvent) -> None:
        """Guild join behaviour"""
        await self.pool.execute("INSERT INTO global_config (guild_id) VALUES ($1)", event.guild_id)

        if event.guild.system_channel_id is None:
            return

        me = event.guild.get_my_member()
        channel = event.guild.get_channel(event.guild.system_channel_id)

        if not channel or not (hikari.Permissions.SEND_MESSAGES & lightbulb.utils.permissions_in(channel, me)):
            return

        try:
            embed = hikari.Embed(
                title="Beep Boop!",
                description="""I have been summoned to this server. Type `/` to see what I can do!\n\nIf you have `Manage Server` permissions, you may configure the bot via `/settings`!""",
                color=0xFEC01D,
            )
            embed.set_thumbnail(me.avatar_url)
            await channel.send(embed=embed)
        except hikari.ForbiddenError:
            pass
        logging.info(f"Bot has been added to new guild: {event.guild.name} ({event.guild_id}).")

    async def on_guild_leave(self, event: hikari.GuildLeaveEvent) -> None:
        """Guild removal behaviour"""
        await self.pool.execute("""DELETE FROM global_config WHERE guild_id = $1""", event.guild_id)
        await self.db_cache.wipe(event.guild_id)
        logging.info(f"Bot has been removed from guild {event.guild_id}, correlating data erased.")

    async def backup_bot_db(self) -> None:
        if self.skip_first_db_backup:
            logging.info("Skipping database backup for this day...")
            self.skip_first_db_backup = False
            return

        file = await db_backup.backup_database(self._dsn)
        await self.wait_until_started()

        if self.config.DB_BACKUP_CHANNEL:
            await self.rest.create_message(
                self.config.DB_BACKUP_CHANNEL,
                f"Database Backup: {helpers.format_dt(helpers.utcnow())}",
                attachment=file,
            )
            return logging.info("Daily database backup complete, database backed up to specified Discord channel.")

        logging.info("Daily database backup complete.")
