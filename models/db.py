from __future__ import annotations

import abc
import importlib
import logging
import os
import typing as t
from contextlib import asynccontextmanager

import asyncpg
import hikari

from models.errors import DatabaseStateConflictError

if t.TYPE_CHECKING:
    from models.bot import SnedBot
    from utils.cache import DatabaseCache

logger = logging.getLogger(__name__)


class Database:
    """A database object that wraps an asyncpg pool and provides additional methods for convenience."""

    def __init__(self, app: SnedBot) -> None:
        self._app: SnedBot = app
        self._user = os.getenv("POSTGRES_USER") or "postgres"
        self._host = os.getenv("POSTGRES_HOST") or "sned-db"
        self._db_name = os.getenv("POSTGRES_DB") or "sned"
        self._port = int(os.getenv("POSTGRES_PORT") or 5432)
        self._password = os.environ["POSTGRES_PASSWORD"]
        self._version = os.getenv("POSTGRES_VERSION")
        self._pool: asyncpg.Pool | None = None
        self._schema_version: int | None = None
        self._is_closed: bool = False

        DatabaseModel._db = self
        DatabaseModel._app = self.app

    @property
    def app(self) -> SnedBot:
        """The currently running application."""
        return self._app

    @property
    def user(self) -> str:
        """The currently authenticated database user."""
        return self._user

    @property
    def host(self) -> str:
        """The database hostname the database is connected to."""
        return self._host

    @property
    def db_name(self) -> str:
        """The name of the database this object is connected to."""
        return self._db_name

    @property
    def port(self) -> int:
        """The connection port to use when connecting to the database."""
        return self._port

    @property
    def password(self) -> str:
        """The database password to use when authenticating."""
        return self._password

    @property
    def version(self) -> str | None:
        """The version of PostgreSQL used. May be None if not explicitly specified."""
        return self._version

    @property
    def schema_version(self) -> int:
        """The version of the database schema."""
        if self._schema_version is None:
            raise DatabaseStateConflictError("The schema version is not known.")
        return self._schema_version

    @property
    def pool(self) -> asyncpg.Pool:
        """The connection pool used to connect to the database."""
        if self._pool is None:
            raise DatabaseStateConflictError("The database is not connected.")
        return self._pool

    @property
    def dsn(self) -> str:
        """The connection URI used to connect to the database."""
        return f"postgres://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}"

    async def connect(self) -> None:
        """Start a new connection and create a connection pool."""
        if self._is_closed:
            raise DatabaseStateConflictError("The database is closed.")

        self._pool = await asyncpg.create_pool(dsn=self.dsn)
        await self.build_schema()  # Always check and add missing tables on startup
        self._schema_version = await self.pool.fetchval("""SELECT schema_version FROM schema_info""", column=0)

    async def close(self) -> None:
        """Close the connection pool."""
        if self._is_closed:
            raise DatabaseStateConflictError("The database is closed.")

        await self.pool.close()
        self._is_closed = True

    def terminate(self) -> None:
        """Terminate the connection pool."""
        if self._is_closed:
            raise DatabaseStateConflictError("The database is closed.")

        self.pool.terminate()
        self._is_closed = True

    @asynccontextmanager
    async def acquire(self) -> t.AsyncIterator[asyncpg.Connection]:
        """Acquire a database connection from the connection pool."""
        con = await self.pool.acquire()
        try:
            yield con  # type: ignore
        finally:
            await self.pool.release(con)

    async def execute(self, query: str, *args, timeout: float | None = None) -> str:
        """Execute an SQL command.

        Parameters
        ----------
        query : str
            The SQL query to run.
        args : Tuple[t.Any]
            The arguments for the SQL query.
        timeout : Optional[float], optional
            The timeout in seconds, by default None

        Returns
        -------
        str
            The SQL return code.

        Raises
        ------
        DatabaseStateConflictError
            The application is not connected to the database server.
        """
        return await self.pool.execute(query, *args, timeout=timeout)  # type: ignore

    async def fetch(self, query: str, *args, timeout: float | None = None) -> list[asyncpg.Record]:
        """Run a query and return the results as a list of `Record`.

        Parameters
        ----------
        query : str
            The SQL query to be ran.
        args : Tuple[t.Any]
            The arguments for the SQL query.
        timeout : Optional[float], optional
            The timeout in seconds, by default None

        Returns
        -------
        List[asyncpg.Record]
            A list of records that matched the query parameters.

        Raises
        ------
        DatabaseStateConflictError
            The application is not connected to the database server.
        """
        return await self.pool.fetch(query, *args, timeout=timeout)

    async def executemany(self, command: str, args: t.Tuple[t.Any], *, timeout: float | None = None) -> str:
        """Execute an SQL command for each sequence of arguments in `args`.

        Parameters
        ----------
        command : str
            The SQL query to run.
        args : Tuple[t.Any]
            The arguments for the SQL query.
        timeout : Optional[float], optional
            The timeout in seconds, by default None

        Returns
        -------
        str
            The SQL return code.

        Raises
        ------
        DatabaseStateConflictError
            The application is not connected to the database server.
        """
        return await self.pool.executemany(command, args, timeout=timeout)  # type: ignore

    async def fetchrow(self, query: str, *args, timeout: float | None = None) -> asyncpg.Record:
        """Run a query and return the first row that matched query parameters.

        Parameters
        ----------
        query : str
            The SQL query to be ran.
        args : Tuple[t.Any]
            The arguments for the SQL query.
        timeout : float, optional
            The timeout in seconds, by default None

        Returns
        -------
        asyncpg.Record
            The record that matched query parameters.

        Raises
        ------
        DatabaseStateConflictError
            The application is not connected to the database server.
        """
        return await self.pool.fetchrow(query, *args, timeout=timeout)  # type: ignore

    async def fetchval(self, query: str, *args, column: int = 0, timeout: float | None = None) -> t.Any:
        """Run a query and return a value in the first row that matched query parameters.

        Parameters
        ----------
        query : str
            The SQL query to be ran.
        args : Tuple[t.Any]
            The arguments for the SQL query.
        column : int, optional
            The column to return, by default 0
        timeout : float, optional
            The timeout in seconds, by default None

        Returns
        -------
        Any
            The value that matched the query parameters.

        Raises
        ------
        DatabaseStateConflictError
            The application is not connected to the database server.
        """
        return await self.pool.fetchval(query, *args, column=column, timeout=timeout)

    async def register_guild(self, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> None:
        """Register a new guild in the database. If a guild is not registered, associated data cannot be created for it.
        If the guild is already registered, this function will do nothing.

        Parameters
        ----------
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild to register.

        Raises
        ------
        DatabaseStateConflictError
            The application is not connected to the database server.
        """
        await self.execute(
            """INSERT INTO global_config (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING""",
            hikari.Snowflake(guild),
        )

    async def wipe_guild(self, guild: hikari.SnowflakeishOr[hikari.PartialGuild], *, keep_record: bool = True) -> None:
        """Wipe a guild's data from the database. This will remove all associated data to this guild.

        Parameters
        ----------
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild to wipe.
        keep_record : bool, optional
            Whether to keep the guild's record in the database, by default True

        Raises
        ------
        DatabaseStateConflictError
            The application is not connected to the database server.
        """
        async with self.acquire() as con:
            await con.execute("""DELETE FROM global_config WHERE guild_id = $1""", hikari.Snowflake(guild))
            if keep_record:
                await con.execute("""INSERT INTO global_config (guild_id) VALUES ($1)""", hikari.Snowflake(guild))

        await DatabaseModel._db_cache.wipe(hikari.Snowflake(guild))

    async def _increment_schema_version(self) -> None:
        """Increment the schema version."""
        record = await self.fetchrow(
            """UPDATE schema_info SET schema_version = schema_version + 1 RETURNING schema_version"""
        )
        self._schema_version = record["schema_version"]

    async def _do_sql_migration(self, filename: str) -> None:
        """Apply an SQL file as a migration to the database."""
        try:
            migration_version = int(filename[:-4])
        except ValueError:
            logger.warning(
                f"Invalid migration file found: '{filename}' Migration filenames must be integers and have a '.sql' extension."
            )
            return

        path = os.path.join(self._app.base_dir, "db", "migrations", filename)

        if migration_version <= self.schema_version or not os.path.isfile(path):
            return

        with open(os.path.join(self._app.base_dir, "db", "migrations", filename)) as file:
            await self.execute(file.read())

        await self._increment_schema_version()
        logger.info(f"Applied database migration: '{filename}'")

    async def _do_python_migration(self, filename: str) -> None:
        """Run a python script as a migration on the database.

        The script must have a `run` function that takes a `Database` object as a parameter.

        Example:
        ```py
        async def run(db: Database) -> None:
            # Migration logic here
        ```
        """
        try:
            migration_version = int(filename[:-3])
        except ValueError:
            logger.warning(
                f"Invalid migration file found: '{filename}' Migration filenames must be integers and have a '.py' extension."
            )
            return

        path = os.path.join(self._app.base_dir, "db", "migrations", filename)

        if migration_version <= self.schema_version or not os.path.isfile(path):
            return

        module = importlib.import_module(f"db.migrations.{filename[:-3]}")
        await module.run(self)
        await self._increment_schema_version()
        logger.info(f"Applied database migration: '{filename}'")

    async def build_schema(self) -> None:
        """Build the initial schema for the database if one doesn't already exist."""
        async with self.acquire() as con:
            with open(os.path.join(self._app.base_dir, "db", "schema.sql")) as file:
                await con.execute(file.read())

    async def update_schema(self) -> None:
        """Update the database schema and apply any pending migrations.
        This also creates the initial schema structure if one does not exist.
        """
        async with self.acquire() as con:
            with open(os.path.join(self._app.base_dir, "db", "schema.sql")) as file:
                await con.execute(file.read())

            schema_version = await con.fetchval("""SELECT schema_version FROM schema_info""", column=0)
            if not isinstance(schema_version, int):
                raise ValueError(f"Schema version not found or invalid. Expected integer, found '{schema_version}'.")

            for filename in sorted(os.listdir(os.path.join(self._app.base_dir, "db", "migrations"))):
                if filename.endswith(".py"):
                    await self._do_python_migration(filename)
                elif filename.endswith(".sql"):
                    await self._do_sql_migration(filename)

        logger.info("Database schema is up to date!")


class DatabaseModel(abc.ABC):
    """Common base-class for all database model objects."""

    _db: Database
    _app: SnedBot
    _db_cache: DatabaseCache


# Copyright (C) 2022-present hypergonial

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
