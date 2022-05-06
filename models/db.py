from __future__ import annotations

import abc
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
        self._pool: t.Optional[asyncpg.Pool] = None
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
    def version(self) -> t.Optional[str]:
        """The version of PostgreSQL used. May be None if not explicitly specified."""
        return self._version

    @property
    def dsn(self) -> str:
        """The connection URI used to connect to the database."""
        return f"postgres://{self.user}:{self.password}@{self.host}:{self.port}/{self.db_name}"

    async def connect(self) -> None:
        """Start a new connection and create a connection pool."""
        if self._is_closed:
            raise DatabaseStateConflictError("The database is closed.")

        self._pool = await asyncpg.create_pool(dsn=self.dsn)

    async def close(self) -> None:
        """Close the connection pool."""
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")
        if self._is_closed:
            raise DatabaseStateConflictError("The database is closed.")

        await self._pool.close()
        self._is_closed = True

    def terminate(self) -> None:
        """Terminate the connection pool."""
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")
        if self._is_closed:
            raise DatabaseStateConflictError("The database is closed.")

        self._pool.terminate()
        self._is_closed = True

    @asynccontextmanager
    async def acquire(self) -> t.AsyncIterator[asyncpg.Connection]:
        """Acquire a database connection from the connection pool."""
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        con = await self._pool.acquire()
        try:
            yield con
        finally:
            await self._pool.release(con)

    async def execute(self, query: str, *args, timeout: t.Optional[float] = None) -> str:
        """Execute an SQL command.

        Parameters
        ----------
        query : str
            The SQL query to run.
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

        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        return await self._pool.execute(query, *args, timeout=timeout)  # type: ignore

    async def fetch(self, query: str, *args, timeout: t.Optional[float] = None) -> t.List[asyncpg.Record]:
        """Run a query and return the results as a list of `Record`.

        Parameters
        ----------
        query : str
            The SQL query to be ran.
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
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        return await self._pool.fetch(query, *args, timeout=timeout)

    async def executemany(self, command: str, args: t.Tuple[t.Any], *, timeout: t.Optional[float] = None) -> str:
        """Execute an SQL command for each sequence of arguments in `args`.

        Parameters
        ----------
        query : str
            The SQL query to run.
        args : Tuple[t.Any]
            Tuples of arguments to execute.
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
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        return await self._pool.executemany(command, args, timeout=timeout)  # type: ignore

    async def fetchrow(self, query: str, *args, timeout: t.Optional[float] = None) -> asyncpg.Record:
        """Run a query and return the first row that matched query parameters.

        Parameters
        ----------
        query : str
            The SQL query to be ran.
        timeout : t.Optional[float], optional
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
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        return await self._pool.fetchrow(query, *args, timeout=timeout)

    async def fetchval(self, query: str, *args, column: int = 0, timeout: t.Optional[float] = None) -> t.Any:
        """Run a query and return a value in the first row that matched query parameters.

        Parameters
        ----------
        query : str
            The SQL query to be ran.
        timeout : t.Optional[float], optional
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
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        return await self._pool.fetchval(query, *args, column=column, timeout=timeout)

    async def wipe_guild(self, guild: hikari.SnowflakeishOr[hikari.PartialGuild], *, keep_record: bool = True) -> None:
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        async with self.acquire() as con:
            await con.execute("""DELETE FROM global_config WHERE guild_id = $1""", hikari.Snowflake(guild))
            if keep_record:
                await con.execute("""INSERT INTO global_config (guild_id) VALUES ($1)""", hikari.Snowflake(guild))

        await DatabaseModel._db_cache.wipe(hikari.Snowflake(guild))

    async def update_schema(self) -> None:
        """Update the database schema and apply any pending migrations.
        This also creates the initial schema structure if one does not exist."""

        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        async with self.acquire() as con:
            with open(os.path.join(self._app.base_dir, "db", "schema.sql")) as file:
                await con.execute(file.read())

            schema_version = await con.fetchval("""SELECT schema_version FROM schema_info""", column=0)
            if not isinstance(schema_version, int):
                raise ValueError(f"Schema version not found or invalid. Expected integer, found '{schema_version}'.")

            for filename in sorted(os.listdir(os.path.join(self._app.base_dir, "db", "migrations"))):
                if not filename.endswith(".sql"):
                    continue

                try:
                    migration_version = int(filename[:-4])
                except ValueError:
                    logger.warning(
                        f"Invalid migration file found: '{filename}' Migration filenames must be integers and have a '.sql' extension."
                    )
                    continue

                path = os.path.join(self._app.base_dir, "db", "migrations", filename)

                if migration_version <= schema_version or not os.path.isfile(path):
                    continue

                with open(os.path.join(self._app.base_dir, "db", "migrations", filename)) as file:
                    await con.execute(file.read())

                await con.execute("""UPDATE schema_info SET schema_version = $1""", migration_version)
                logger.info(f"Applied database migration: '{filename}'")

        logger.info("Database schema is up to date!")


class DatabaseModel(abc.ABC):
    """Common base-class for all database model objects."""

    _db: Database
    _app: SnedBot
    _db_cache: DatabaseCache


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
