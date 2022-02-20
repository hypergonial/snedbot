import asyncio
import os

import asyncpg
from config import Config

# Modify this line & change it to your PSQL DB address
# Do not modify the variables, DBPASS is retrieved from .env,
# while db_name is decided on runtime.
config = Config()
dsn = config.POSTGRES_DSN

try:
    print(
        """Sned-Bot Database Initialization

    The following steps need to be taken BEFORE running this script:

    Create a postgresql database on the address specified in the DSN,
    and point the postgres_dsn in config.py to it. The database's name 
    must be either 'sned' or 'sned_exp' with default user 'postgres'.
    Current DSN: {dsn}"""
    )

    while True:
        is_dev_mode = input(
            "Do you want to initialize the database for the stable or the developer mode version? Type 'stable' for stable, 'dev' for developer.\n> "
        )
        if is_dev_mode in ["stable", "dev"]:
            if is_dev_mode == "stable":
                db_name = "sned"
            else:
                db_name = "sned_exp"
            break
        else:
            print("Invalid input. Try again.\n")

    async def init_tables():
        """
        Create all tables necessary for the functioning of this bot.
        """

        pool = await asyncpg.create_pool(dsn=dsn.format(db_name=db_name))
        async with pool.acquire() as con:
            print("Creating tables...")

            # To allow for levenshtein()
            await con.execute("""CREATE EXTENSION IF NOT EXISTS fuzzystrmatch""")

            await con.execute(
                """
                CREATE TABLE IF NOT EXISTS public.global_config
                (
                    guild_id bigint NOT NULL,
                    prefix text[],
                    PRIMARY KEY (guild_id)
                )"""
            )
            await con.execute(
                """
                CREATE TABLE IF NOT EXISTS public.users
                (
                    user_id bigint NOT NULL,
                    guild_id bigint NOT NULL,
                    flags json,
                    warns integer NOT NULL DEFAULT 0,
                    notes text[],
                    PRIMARY KEY (user_id, guild_id),
                    FOREIGN KEY (guild_id)
                        REFERENCES global_config (guild_id)
                        ON DELETE CASCADE
                )"""
            )
            # guild_id is always needed in table, so I just hacked it in c:
            # the table is not guild-specific though
            await con.execute(
                """
                CREATE TABLE IF NOT EXISTS public.blacklist
                (
                    guild_id integer NOT NULL DEFAULT 0,
                    user_id bigint NOT NULL,
                    PRIMARY KEY (user_id)
                )
            """
            )
            await con.execute(
                """
                CREATE TABLE IF NOT EXISTS public.guild_blacklist
                (
                    guild_id bigint NOT NULL
                )"""
            )

            await con.execute(
                """
                CREATE TABLE IF NOT EXISTS public.mod_config
                (
                    guild_id bigint NOT NULL,
                    dm_users_on_punish bool NOT NULL DEFAULT true,
                    is_ephemeral bool NOT NULL DEFAULT false,
                    automod_policies json NOT NULL DEFAULT '{}',
                    PRIMARY KEY (guild_id),
                    FOREIGN KEY (guild_id)
                        REFERENCES global_config (guild_id)
                        ON DELETE CASCADE
                )"""
            )
            await con.execute(
                """
                CREATE TABLE IF NOT EXISTS public.reports
                (
                    guild_id bigint NOT NULL,
                    is_enabled bool NOT NULL DEFAULT false,
                    channel_id bigint,
                    pinged_role_ids bigint[] DEFAULT '{}',
                    PRIMARY KEY (guild_id),
                    FOREIGN KEY (guild_id)
                        REFERENCES global_config (guild_id)
                        ON DELETE CASCADE
                )"""
            )
            await con.execute(
                """
                    CREATE TABLE IF NOT EXISTS public.timers
                    (
                        id serial NOT NULL,
                        guild_id bigint NOT NULL,
                        user_id bigint NOT NULL,
                        channel_id bigint,
                        event text NOT NULL,
                        expires bigint NOT NULL,
                        notes text,
                        PRIMARY KEY (id),
                        FOREIGN KEY (guild_id)
                            REFERENCES global_config (guild_id)
                            ON DELETE CASCADE
                    )"""
            )
            await con.execute(
                """
                    CREATE TABLE IF NOT EXISTS public.button_roles
                    (
                        guild_id bigint NOT NULL,
                        entry_id serial NOT NULL,
                        channel_id bigint NOT NULL,
                        msg_id bigint NOT NULL,
                        emoji text NOT NULL,
                        buttonlabel text,
                        buttonstyle text,
                        role_id bigint NOT NULL,
                        PRIMARY KEY (guild_id, entry_id),
                        FOREIGN KEY (guild_id)
                            REFERENCES global_config (guild_id)
                            ON DELETE CASCADE
                    )"""
            )
            await con.execute(
                """
                    CREATE TABLE IF NOT EXISTS public.events
                    (
                        guild_id bigint NOT NULL,
                        entry_id text NOT NULL,
                        channel_id bigint NOT NULL,
                        msg_id bigint NOT NULL,
                        recurring_in bigint,
                        permitted_roles bigint[],
                        categories json NOT NULL,
                        PRIMARY KEY (guild_id, entry_id),
                        FOREIGN KEY (guild_id)
                            REFERENCES global_config (guild_id)
                            ON DELETE CASCADE
                    )
                    """
            )
            await con.execute(
                """
                    CREATE TABLE IF NOT EXISTS public.matchmaking_config
                    (
                        guild_id bigint,
                        init_channel_id bigint,
                        announce_channel_id bigint,
                        lfg_role_id bigint,
                        PRIMARY KEY (guild_id),
                        FOREIGN KEY (guild_id)
                            REFERENCES global_config (guild_id)
                            ON DELETE CASCADE
                    )"""
            )
            await con.execute(
                """
                    CREATE TABLE IF NOT EXISTS public.matchmaking_listings
                    (
                        id text,
                        ubiname text NOT NULL,
                        host_id bigint NOT NULL,
                        gamemode text NOT NULL,
                        playercount text NOT NULL,
                        DLC text NOT NULL,
                        mods text NOT NULL,
                        timezone text NOT NULL,
                        additional_info text NOT NULL,
                        timestamp bigint NOT NULL,
                        guild_id bigint NOT NULL,
                        PRIMARY KEY (id)
                    )"""
            )
            await con.execute(
                """
                    CREATE TABLE IF NOT EXISTS public.tags
                    (
                        guild_id bigint NOT NULL,
                        tag_name text NOT NULL,
                        tag_owner_id bigint NOT NULL,
                        tag_aliases text[],
                        tag_content text NOT NULL,
                        PRIMARY KEY (guild_id, tag_name),
                        FOREIGN KEY (guild_id)
                            REFERENCES global_config (guild_id)
                            ON DELETE CASCADE
                    )"""
            )
            await con.execute(
                """
                    CREATE TABLE IF NOT EXISTS public.log_config
                    (
                        guild_id bigint NOT NULL,
                        log_channels json,
                        color bool NOT NULL DEFAULT true,
                        PRIMARY KEY (guild_id),
                        FOREIGN KEY (guild_id)
                            REFERENCES global_config (guild_id)
                            ON DELETE CASCADE
                    )"""
            )
            await con.execute(
                """
                    CREATE TABLE IF NOT EXISTS public.ktp
                    (
                        guild_id bigint NOT NULL,
                        ktp_id serial NOT NULL,
                        ktp_channel_id bigint NOT NULL,
                        ktp_msg_id bigint NOT NULL,
                        ktp_content text NOT NULL,
                        PRIMARY KEY (guild_id, ktp_id),
                        FOREIGN KEY (guild_id)
                            REFERENCES global_config (guild_id)
                            ON DELETE CASCADE
                    )"""
            )
            await con.execute(
                """
                    CREATE TABLE IF NOT EXISTS public.starboard
                    (
                        guild_id bigint NOT NULL,
                        is_enabled bool NOT NULL DEFAULT false,
                        star_limit smallint NOT NULL DEFAULT 5,
                        channel_id bigint,
                        excluded_channels bigint[] DEFAULT '{}',
                        PRIMARY KEY (guild_id),
                        FOREIGN KEY (guild_id)
                            REFERENCES global_config (guild_id)
                            ON DELETE CASCADE
                    )"""
            )
            await con.execute(
                """
                    CREATE TABLE IF NOT EXISTS public.starboard_entries
                    (
                        guild_id bigint NOT NULL,
                        channel_id bigint NOT NULL,
                        orig_msg_id bigint NOT NULL,
                        entry_msg_id bigint NOT NULL,
                        PRIMARY KEY (guild_id, channel_id, orig_msg_id),
                        FOREIGN KEY (guild_id)
                            REFERENCES global_config (guild_id)
                            ON DELETE CASCADE
                    )"""
            )

        await pool.close()
        print("Tables created, database is ready!")

    asyncio.run(init_tables())
    input("\nPress enter to exit...")

except KeyboardInterrupt:
    print("\nKeyboard interrupt received, exiting...")
