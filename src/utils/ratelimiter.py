from __future__ import annotations

import abc
import asyncio
import sys
import time
import traceback
import typing as t
from collections import deque

import attr

if t.TYPE_CHECKING:
    import hikari


# FIXME: Destroy module
class ContextLike(t.Protocol):
    """An object that has common attributes of a context."""

    @property
    def author(self) -> hikari.UndefinedOr[hikari.User]:
        ...

    @property
    def guild_id(self) -> hikari.Snowflake | None:
        ...

    @property
    def channel_id(self) -> hikari.Snowflake:
        ...


@attr.define()
class BucketData:
    """Handles the ratelimiting of a single bucket data. (E.g. a single user or a channel)."""

    reset_at: float
    """The time at which the bucket resets."""
    remaining: int
    """The amount of requests remaining in the bucket."""
    bucket: Bucket
    """The bucket this data belongs to."""
    queue: t.Deque[asyncio.Event] = attr.field(factory=deque)
    """A list of events to set as the iter task proceeds."""
    task: asyncio.Task[t.Any] | None = attr.field(default=None)
    """The task that is currently iterating over the queue."""

    @classmethod
    def for_bucket(cls, bucket: Bucket) -> BucketData:
        """Create a new BucketData for a Bucket."""
        return cls(
            bucket=bucket,
            reset_at=time.monotonic() + bucket.period,
            remaining=bucket.limit,
        )

    def start_queue(self) -> None:
        """Start the queue of a BucketData.
        This will start setting events in the queue until the bucket is ratelimited.
        """
        if self.task is None:
            self.task = asyncio.create_task(self._iter_queue())

    def reset(self) -> None:
        """Reset the ratelimit."""
        self.remaining = self.bucket.limit
        self.reset_at = time.monotonic() + self.bucket.period

    async def _iter_queue(self) -> None:
        """Iterate over the queue of a BucketData and set events."""
        try:
            if self.remaining <= 0 and self.reset_at > time.monotonic():
                # Sleep until ratelimit expires
                sleep_time = self.reset_at - time.monotonic()
                await asyncio.sleep(sleep_time)
                self.reset()
            elif self.reset_at <= time.monotonic():
                self.reset()

            # Set events while not ratelimited
            while self.remaining > 0 and self.queue:
                self.remaining -= 1
                self.queue.popleft().set()

            self.task = None

        except Exception as e:
            print(f"Task Exception was never retrieved: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)


class Bucket(abc.ABC):
    """Abstract class for ratelimiter buckets."""

    def __init__(self, period: float, limit: int, wait: bool = True) -> None:
        """Abstract class for ratelimiter buckets.

        Parameters
        ----------
        period : float
            The period, in seconds, after which the quota resets.
        limit : int
            The amount of requests allowed in a quota.
        wait : bool
            Determines if the ratelimiter should wait in
            case of hitting a ratelimit.
        """
        self.period: float = period
        self.limit: int = limit
        self.wait: bool = wait
        self._bucket_data: t.Dict[str, BucketData] = {}

    @abc.abstractmethod
    def get_key(self, ctx: ContextLike) -> str:
        """Get key for ratelimiter bucket."""

    def is_rate_limited(self, ctx: ContextLike) -> bool:
        """Returns a boolean determining if the ratelimiter is ratelimited or not."""
        now = time.monotonic()

        if data := self._bucket_data.get(self.get_key(ctx)):
            if data.reset_at <= now:
                return False
            return data.remaining <= 0
        return False

    async def acquire(self, ctx: ContextLike) -> None:
        """Acquire a ratelimit, block execution if ratelimited and wait is True."""
        event = asyncio.Event()

        # Get or insert bucket data
        data = self._bucket_data.setdefault(self.get_key(ctx), BucketData.for_bucket(self))
        data.queue.append(event)
        data.start_queue()

        if self.wait:
            await event.wait()

    def reset(self, ctx: ContextLike) -> None:
        """Reset the ratelimit for a given context."""
        if data := self._bucket_data.get(self.get_key(ctx)):
            data.reset()


class GlobalBucket(Bucket):
    """Ratelimiter bucket for global ratelimits."""

    def get_key(self, _: ContextLike) -> str:
        return "amongus"


class GuildBucket(Bucket):
    """Ratelimiter bucket for guilds.

    Note that all ContextLike objects must have a guild_id set.
    """

    def get_key(self, ctx: ContextLike) -> str:
        if not ctx.guild_id:
            raise KeyError("guild_id is not set.")
        return str(ctx.guild_id)


class ChannelBucket(Bucket):
    """Ratelimiter bucket for channels."""

    def get_key(self, ctx: ContextLike) -> str:
        return str(ctx.channel_id)


class UserBucket(Bucket):
    """Ratelimiter bucket for users.

    Note that all ContextLike objects must have an author set.
    """

    def get_key(self, ctx: ContextLike) -> str:
        if not ctx.author:
            raise KeyError("author is not set.")
        return str(ctx.author.id)


class MemberBucket(Bucket):
    """Ratelimiter bucket for members.

    Note that all ContextLike objects must have an author and guild_id set.
    """

    def get_key(self, ctx: ContextLike) -> str:
        if not ctx.author or not ctx.guild_id:
            raise KeyError("author or guild_id is not set.")
        return str(ctx.author.id) + str(ctx.guild_id)


class RateLimiter:
    def __init__(self, period: float, limit: int, bucket: t.Type[Bucket], wait: bool = True) -> None:
        """Rate Limiter implementation for Sned.

        Parameters
        ----------
        period : float
            The period, in seconds, after which the quota resets.
        limit : int
            The amount of requests allowed in a quota.
        bucket : Bucket
            The bucket to handle this under.
        wait : bool
            Determines if the ratelimiter should wait in
            case of hitting a ratelimit.
        """
        self.bucket: Bucket = bucket(period, limit, wait)

    def is_rate_limited(self, ctx: ContextLike) -> bool:
        """Returns a boolean determining if the ratelimiter is ratelimited or not."""
        return self.bucket.is_rate_limited(ctx)

    async def acquire(self, ctx: ContextLike) -> None:
        """Acquire a ratelimit, block execution if ratelimited and wait is True."""
        return await self.bucket.acquire(ctx)

    def reset(self, ctx: ContextLike) -> None:
        """Reset the ratelimit for a given context."""
        self.bucket.reset(ctx)


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
