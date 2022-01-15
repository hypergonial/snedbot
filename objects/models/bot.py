import logging
import os
import asyncio
import asyncpg

import hikari
from objects.config_handler import ConfigHandler
from objects.utils import cache, scheduler
import lightbulb


class SnedBot(lightbulb.BotApp):
    def __init__(self, config: dict):
        self.loop = asyncio.get_event_loop()
        self._started = asyncio.Event()

        cache_settings = hikari.CacheSettings(
            components=hikari.CacheComponents.ALL, max_messages=10000, max_dm_channel_ids=50
        )
        intents = (
            hikari.Intents.GUILDS
            | hikari.Intents.GUILD_MEMBERS
            | hikari.Intents.GUILD_BANS
            | hikari.Intents.GUILD_EMOJIS
            | hikari.Intents.GUILD_MESSAGES
            | hikari.Intents.GUILD_INVITES
            | hikari.Intents.ALL_MESSAGE_REACTIONS
        )

        self.experimental = config["experimental"]
        if self.experimental:
            default_enabled_guilds = (config["home_guild"]) if isinstance(config["home_guild"], int) else ()
            db_name = "sned_exp"
        else:
            default_enabled_guilds = ()
            db_name = "sned"

        activity = hikari.Activity(name="to @Sned", type=hikari.ActivityType.LISTENING)

        super().__init__(
            token=config["token"],
            cache_settings=cache_settings,
            default_enabled_guilds=default_enabled_guilds,
            intents=intents,
        )

        config.pop("token")

        # Initizaling configuration and database
        self.config = config
        self.dsn = self.config["postgres_dsn"].format(db_name=db_name)
        self.pool = self.loop.run_until_complete(asyncpg.create_pool(dsn=self.dsn))

        # Some global variables
        self.base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        self.skip_db_backup = True
        self.is_ready = False
        self.user_id = None

        # Color scheme
        self.error_color = 0xFF0000
        self.warn_color = 0xFFCC4D
        self.embed_blue = 0x009DFF
        self.embed_green = 0x77B255
        self.unknown_color = 0xBE1931
        self.misc_color = 0xC2C2C2

        self.start_listeners()

    def start_listeners(self) -> None:
        """
        Start all listeners located in this class.
        """
        self.subscribe(hikari.StartedEvent, self.on_startup)
        self.subscribe(hikari.MessageEvent, self.on_message)
        self.subscribe(hikari.StoppingEvent, self.on_stopping)
        self.subscribe(hikari.StoppedEvent, self.on_stop)

    async def wait_until_ready(self) -> None:
        """
        Wait until the bot has started up
        """
        await asyncio.wait_for(self._started.wait(), timeout=None)

    async def on_startup(self, event: hikari.StartedEvent) -> None:

        user = self.get_me()
        self.is_ready = True
        self._started.set()
        self.user_id = user.id

        self.db_cache = cache.Caching(self)
        self.global_config = ConfigHandler(self)
        self.scheduler = scheduler.Scheduler(self)

        logging.info(f"Startup complete, initialized as {user}")

        if self.experimental:
            logging.warning("\n--------------\nExperimental mode is enabled!\n--------------")

        # Insert all guilds the bot is member of into the db global config on startup
        async with self.pool.acquire() as con:
            for guild in self.cache.get_guilds_view():
                await con.execute(
                    """
                INSERT INTO global_config (guild_id) VALUES ($1)
                ON CONFLICT (guild_id) DO NOTHING""",
                    guild,
                )

    async def on_stopping(self, event: hikari.StoppingEvent) -> None:
        self.is_ready = False
        logging.info("Bot is shutting down...")

    async def on_stop(self, event: hikari.StoppedEvent) -> None:
        await self.pool.close()
        logging.info("Closed database connection.")

    async def on_message(self, event: hikari.MessageEvent) -> None:
        if self.is_ready and self.db_cache.is_ready and event.is_human:
            mentions = [f"<@{self.user_id}>", f"<@!{self.user_id}>"]

            if event.content in mentions:
                embed = hikari.Embed(
                    title="Beep Boop!",
                    description="Use `/` to access my commands and see what I can do!\n\n**Spoiler:** Not much as I am currently being rewritten, send help!",
                    color=0xFEC01D,
                )
                embed.set_thumbnail(self.get_me().avatar_url)
                await event.message.respond(embed=embed)
