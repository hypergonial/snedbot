from __future__ import annotations

import abc
import os
import typing as t
from contextlib import asynccontextmanager

import asyncpg
import hikari

from models.errors import DatabaseStateConflictError

if t.TYPE_CHECKING:
    from utils.cache import DatabaseCache


class Database:
    """A database object that wraps an asyncpg pool and provides additional methods for convenience."""

    def __init__(self) -> None:
        self._user = os.getenv("POSTGRES_USER") or "postgres"
        self._host = os.getenv("POSTGRES_HOST") or "sned-db"
        self._db_name = os.getenv("POSTGRES_DB") or "sned"
        self._port = int(os.getenv("POSTGRES_PORT") or 5432)
        self._password = os.environ["POSTGRES_PASSWORD"]
        self._version = os.getenv("POSTGRES_VERSION")
        self._pool: t.Optional[asyncpg.Pool] = None
        self._is_closed: bool = False

        DatabaseModel._db = self

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
        return f"postgres://{self.user}:{self.password}@{self.host}/{self.db_name}"

    async def connect(self) -> None:
        if self._is_closed:
            raise DatabaseStateConflictError("The database is closed.")

        self._pool = await asyncpg.create_pool(dsn=self.dsn)

    async def close(self) -> None:
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")
        if self._is_closed:
            raise DatabaseStateConflictError("The database is closed.")

        await self._pool.close()
        self._is_closed = True

    def terminate(self) -> None:
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")
        if self._is_closed:
            raise DatabaseStateConflictError("The database is closed.")

        self._pool.terminate()
        self._is_closed = True

    @asynccontextmanager
    async def acquire(self) -> t.AsyncIterator[asyncpg.Connection]:
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        con = await self._pool.acquire()
        try:
            yield con
        finally:
            await self._pool.release(con)

    async def execute(self, query: str, *args, timeout: t.Optional[float] = None) -> str:
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        return await self._pool.execute(query, *args, timeout=timeout)  # type: ignore

    async def fetch(self, query: str, *args, timeout: t.Optional[float] = None) -> t.List[asyncpg.Record]:
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        return await self._pool.fetch(query, *args, timeout=timeout)

    async def executemany(self, command: str, args: t.Tuple[t.Any], *, timeout: t.Optional[float] = None) -> str:
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        return await self._pool.executemany(command, args, timeout=timeout)  # type: ignore

    async def fetchrow(self, query: str, *args, timeout: t.Optional[float] = None) -> asyncpg.Record:
        if not self._pool:
            raise DatabaseStateConflictError("The database is not connected.")

        return await self._pool.fetchrow(query, *args, timeout=timeout)

    async def fetchval(self, query: str, *args, column: int = 0, timeout: t.Optional[float] = None) -> t.Any:
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


class DatabaseModel(abc.ABC):
    """Common base-class for all database model objects."""

    _db: Database
    _db_cache: DatabaseCache
