import datetime
import logging
import os
import pathlib
from contextlib import suppress

import aiohttp
import arc
import hikari
import kosu
import miru

import src.utils.db_backup as db_backup
from src.config import Config
from src.models.audit_log import AuditLogCache
from src.models.db import Database
from src.models.mod_actions import ModActions
from src.utils import cache, helpers, scheduler


class SnedClient(arc.GatewayClientBase[hikari.GatewayBot]):
    def __init__(self, config: Config) -> None:
        cache_settings = hikari.impl.CacheSettings(
            components=hikari.api.CacheComponents.ALL, max_messages=100000, max_dm_channel_ids=50
        )
        intents = (
            hikari.Intents.GUILDS
            | hikari.Intents.GUILD_MEMBERS
            | hikari.Intents.GUILD_MODERATION
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

        bot = hikari.GatewayBot(token=token, cache_settings=cache_settings, intents=intents, banner=None)

        super().__init__(
            bot,
            default_enabled_guilds=default_enabled_guilds,
            is_dm_enabled=False,
        )

        # Initizaling configuration and database
        self._config = config
        self._db = Database(self)
        self._session: aiohttp.ClientSession | None = None
        self._db_cache = cache.DatabaseCache(self)
        self._mod = ModActions(self)
        self._miru = miru.Client.from_arc(self)

        # Some global variables
        self._base_dir = str(pathlib.Path(os.path.abspath(__file__)).parents[2])
        self._db_backup_loop = arc.utils.IntervalLoop(self.backup_db, seconds=3600 * 24)
        self.skip_db_backup = True  # Set to False to backup DB on bot startup too
        self._user_id: hikari.Snowflake | None = None
        self._perspective: kosu.Client | None = None
        self._scheduler = scheduler.Scheduler(self)
        self._audit_log_cache: AuditLogCache = AuditLogCache(self)
        self._initial_guilds: list[hikari.Snowflake] = []
        self._start_time: datetime.datetime | None = None

    @property
    def user_id(self) -> hikari.Snowflake:
        """The application user's ID."""
        if self._user_id is None:
            raise hikari.ComponentStateConflictError("The bot is not yet initialized, user_id is unavailable.")

        return self._user_id

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
    def audit_log_cache(self) -> AuditLogCache:
        """The audit log cache instance of the bot."""
        return self._audit_log_cache

    @property
    def miru(self) -> miru.Client:
        """The miru client of the bot."""
        return self._miru

    @property
    def start_time(self) -> datetime.datetime:
        """The datetime when the bot started up."""
        if not self.is_started or self._start_time is None:
            raise hikari.ComponentStateConflictError("The bot is not started yet, 'start_time' cannot be retrieved.")
        return self._start_time

    def start_listeners(self) -> None:
        """Start all listeners located in this class."""
        self.subscribe(hikari.StartingEvent, self.on_starting)
        self.subscribe(hikari.StartedEvent, self.on_started)
        self.subscribe(hikari.GuildAvailableEvent, self.on_guild_available)
        self.subscribe(arc.StartedEvent, self.on_arc_started)
        self.subscribe(hikari.MessageCreateEvent, self.on_message)
        self.subscribe(hikari.StoppingEvent, self.on_stopping)
        self.subscribe(hikari.StoppedEvent, self.on_stop)
        self.subscribe(hikari.GuildJoinEvent, self.on_guild_join)
        self.subscribe(hikari.GuildLeaveEvent, self.on_guild_leave)

    async def on_guild_available(self, event: hikari.GuildAvailableEvent) -> None:
        if self.is_started:
            return
        self._initial_guilds.append(event.guild_id)

    async def on_starting(self, _: hikari.StartingEvent) -> None:
        # Connect to the database, update schema, apply pending migrations
        await self.db.connect()
        await self.db.update_schema()
        # Start scheduler, DB cache
        await self.db_cache.start()
        self.scheduler.start()
        await self._audit_log_cache.start()

        if perspective_api_key := os.getenv("PERSPECTIVE_API_KEY"):
            self._perspective = kosu.Client(perspective_api_key, do_not_store=True)

        # Load all extensions
        self.load_extensions_from(os.path.join(self.base_dir, "src", "extensions"))

    async def on_started(self, _: hikari.StartedEvent) -> None:
        self._db_backup_loop.start()

        user = self.app.get_me()
        self._user_id = user.id if user else None

        logging.info(f"Startup complete, initialized as {user}.")
        activity = hikari.Activity(name="@Sned", type=hikari.ActivityType.LISTENING)
        await self.app.update_presence(activity=activity)

        if self.dev_mode:
            logging.warning("Developer mode is enabled!")

    async def on_arc_started(self, _: arc.StartedEvent) -> None:
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
        self._start_time = helpers.utcnow()
        self.unsubscribe(hikari.GuildAvailableEvent, self.on_guild_available)

    async def on_stopping(self, _: hikari.StoppingEvent) -> None:
        logging.info("Bot is shutting down...")
        self.scheduler.stop()

    async def on_stop(self, _: hikari.StoppedEvent) -> None:
        await self.db.close()
        logging.info("Closed database connection.")

    async def on_message(self, event: hikari.MessageCreateEvent) -> None:
        if not event.content:
            return

        if self.is_started and self.db_cache.is_ready and event.is_human:
            mentions = [f"<@{self.user_id}>", f"<@!{self.user_id}>"]

            if event.content in mentions:
                me = self.app.get_me()
                await event.message.respond(
                    embed=hikari.Embed(
                        title="Beep Boop!",
                        description="Use `/` to access my commands and see what I can do!",
                        color=0xFEC01D,
                    ).set_thumbnail(me.avatar_url if me else None)
                )

    async def on_guild_join(self, event: hikari.GuildJoinEvent) -> None:
        await self.db.register_guild(event.guild_id)

        if event.guild.system_channel_id is None:
            return

        me = event.guild.get_my_member()
        channel = event.guild.get_channel(event.guild.system_channel_id)

        assert me is not None

        # FIXME: Get muh toolbox
        if not channel or not (hikari.Permissions.SEND_MESSAGES & lightbulb.utils.permissions_in(channel, me)):
            return

        assert isinstance(channel, hikari.TextableGuildChannel)

        with suppress(hikari.ForbiddenError):
            await channel.send(
                embed=hikari.Embed(
                    title="Beep Boop!",
                    description="""I have been summoned to this server. Type `/` to see what I can do!\n\nIf you have `Manage Server` permissions, you may configure the bot via `/settings`!""",
                    color=0xFEC01D,
                ).set_thumbnail(me.avatar_url)
            )
        logging.info(f"Bot has been added to new guild: {event.guild.name} ({event.guild_id}).")

    async def on_guild_leave(self, event: hikari.GuildLeaveEvent) -> None:
        await self.db.wipe_guild(event.guild_id, keep_record=False)
        logging.info(f"Bot has been removed from guild {event.guild_id}, correlating data erased.")

    async def backup_db(self) -> None:
        """Backs up the database to a file and, if configured, sends it to the specified channel."""
        if self.skip_db_backup:
            logging.info("Skipping database backup for this day...")
            self.skip_db_backup = False
            return

        file = await db_backup.backup_database()
        await self.wait_until_started()

        if self.config.DB_BACKUP_CHANNEL:
            await self.rest.create_message(
                self.config.DB_BACKUP_CHANNEL,
                f"Database Backup: {helpers.format_dt(helpers.utcnow())}",
                attachment=file,
            )
            return logging.info("Database backup complete, database backed up and sent to specified Discord channel.")

        logging.info("Database backup complete.")


SnedContext = arc.Context[SnedClient]
SnedPlugin = arc.GatewayPluginBase[SnedClient]
