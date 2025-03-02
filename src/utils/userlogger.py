from __future__ import annotations

import asyncio
import datetime
import enum
import json
import logging
import sys
import traceback
import typing as t

import hikari
import toolbox

if t.TYPE_CHECKING:
    from src.models.client import SnedClient

logger = logging.getLogger(__name__)


class LogEvent(enum.Enum):
    """Enum for all valid log events."""

    BAN = "ban"
    """Logs related to bans and unbans"""
    KICK = "kick"
    """Logs related to kicks"""
    TIMEOUT = "timeout"
    """Logs related to timeouts & timeout removals"""
    MESSAGE_DELETE = "message_delete"
    """Logs related to messages voluntarily deleted by users"""
    MESSAGE_DELETE_MOD = "message_delete_mod"
    """Logs related to messages deleted by moderators"""
    MESSAGE_EDIT = "message_edit"
    """Logs related to message edits"""
    BULK_DELETE = "bulk_delete"
    """Logs related to bulk message deletions by moderators"""
    FLAGS = "flags"
    """Logs related to automod message flagging"""
    ROLES = "roles"
    """Logs related to role creation, deletion updates & assignments"""
    CHANNELS = "channels"
    """Logs related to channel creation, deletion & updates"""
    MEMBER_JOIN = "member_join"
    """Logs related to member joins"""
    MEMBER_LEAVE = "member_leave"
    """Logs related to member leaves, this should not include kicks or bans"""
    NICKNAME = "nickname"
    """Logs related to nickname changes"""
    GUILD_SETTINGS = "guild_settings"
    """Logs related to guild setting changes"""
    WARN = "warn"
    """Logs related to new warnings, warning removals & clears"""


class UserLogger:
    """Handles the logging of audit log & other related events."""

    def __init__(self, client: SnedClient) -> None:
        self._client = client
        self._queue: dict[hikari.Snowflake, list[hikari.Embed]] = {}
        self._frozen_guilds: list[hikari.Snowflake] = []
        self._task: asyncio.Task[None] = self._client.create_task(self._iter_queue())

    async def _iter_queue(self) -> None:
        """Iter queue and bulk-send embeds."""
        try:
            while True:
                if not self._client.is_started:
                    await self._client.wait_until_started()

                for channel_id, embeds in self._queue.items():
                    if not embeds:
                        continue

                    embed_chunks: list[list[hikari.Embed]] = [[]]
                    for embed in embeds:
                        # If combined length of all embeds is below 6000 and there are less than 10 embeds in chunk, add to chunk
                        if (
                            sum([embed.total_length() for embed in embed_chunks[-1]]) + embed.total_length()
                        ) <= 6000 and len(embed_chunks[-1]) < 10:
                            embed_chunks[-1].append(embed)
                        # Otherwise make new chunk
                        else:
                            embed_chunks.append([embed])

                    for chunk in embed_chunks:
                        try:
                            await self._client.rest.create_message(channel_id, embeds=chunk)
                        except Exception as exc:
                            logger.warning(f"Failed to send log embed chunk to channel {channel_id}: {exc}")

                    self._queue[channel_id] = []

                await asyncio.sleep(10.0)

        except Exception as error:
            print("Encountered exception in userlog queue iteration:", error)
            traceback.print_exception(error.__class__, error, error.__traceback__, file=sys.stderr)

    async def get_log_channel_id(
        self, log_event: LogEvent, guild: hikari.SnowflakeishOr[hikari.PartialGuild]
    ) -> int | None:
        """Get the channel ID for a given log event.

        Parameters
        ----------
        log_event : str
            The event to get the channel ID for.
        guild : hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild to get the channel ID for.

        Returns
        -------
        int | None
            The channel ID, if any.

        Raises
        ------
        ValueError
            If an invalid log_event is passed.
        """
        records = await self._client.db_cache.get(table="log_config", guild_id=hikari.Snowflake(guild), limit=1)

        log_channels = json.loads(records[0]["log_channels"]) if records and records[0]["log_channels"] else None

        return log_channels.get(log_event.value) if log_channels else None

    async def get_log_channel_ids_view(
        self, guild: hikari.SnowflakeishOr[hikari.PartialGuild]
    ) -> dict[str, int | None]:
        """Return a mapping of log_event:channel_id."""
        records = await self._client.db_cache.get(table="log_config", guild_id=hikari.Snowflake(guild), limit=1)

        log_channels: dict[str, int | None] = (
            json.loads(records[0]["log_channels"]) if records and records[0]["log_channels"] else {}
        )

        for log_event in LogEvent:
            if log_event.value not in log_channels:
                log_channels[log_event.value] = None

        return log_channels

    async def set_log_channel(
        self,
        log_event: LogEvent,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        channel: hikari.SnowflakeishOr[hikari.PartialChannel] | None = None,
    ) -> None:
        """Sets logging channel for a given logging event."""
        guild_id = hikari.Snowflake(guild)
        channel_id = hikari.Snowflake(channel) if channel else None

        log_channels = await self.get_log_channel_ids_view(guild_id)
        log_channels[log_event.value] = channel_id
        await self._client.db.execute(
            """
            INSERT INTO log_config (log_channels, guild_id) VALUES ($1, $2)
            ON CONFLICT (guild_id) DO
            UPDATE SET log_channels = $1""",
            json.dumps(log_channels),
            guild_id,
        )
        await self._client.db_cache.refresh(table="log_config", guild_id=guild_id)

    async def is_color_enabled(self, guild_id: int) -> bool:
        records = await self._client.db_cache.get(table="log_config", guild_id=guild_id, limit=1)
        return records[0]["color"] if records else True

    async def log(
        self,
        log_event: LogEvent,
        log_content: hikari.Embed,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        file: hikari.UndefinedOr[hikari.Resourceish] = hikari.UNDEFINED,
        bypass: bool = False,
    ) -> None:
        """Log log_content into the channel assigned to log_event, if any.

        Parameters
        ----------
        log_event : str
            The channel associated with this event to post it under.
        log_content : hikari.Embed
            What needs to be logged.
        guild: hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild to send the log entry in.
        file : Optional[hikari.File], optional
            An attachment, if any, by default None
        bypass : bool, optional
            If bypassing guild log freeze is desired, by default False
        """
        guild_id = hikari.Snowflake(guild)

        if not self._client.is_started or not self._client.db_cache.is_ready:
            return

        if guild_id in self._frozen_guilds and not bypass:
            return

        log_channel_id = await self.get_log_channel_id(log_event, guild_id)

        if not log_channel_id:
            return

        log_content.timestamp = datetime.datetime.now(datetime.timezone.utc)
        embed = log_content

        # Check if the channel still exists or not, and lazily invalidate it if not
        log_channel = self._client.cache.get_guild_channel(log_channel_id)
        if log_channel is None:
            return await self.set_log_channel(log_event, guild_id, None)
        assert isinstance(log_channel, hikari.TextableGuildChannel)
        assert isinstance(log_channel, hikari.PermissibleGuildChannel)

        me = self._client.cache.get_member(guild_id, self._client.user_id)
        assert me is not None
        perms = toolbox.calculate_permissions(me, log_channel)
        if not (perms & hikari.Permissions.SEND_MESSAGES) or not (perms & hikari.Permissions.EMBED_LINKS):
            # Do not attempt message send if we have no perms
            return

        if file:  # Embeds with attachments will be sent without grouping
            try:
                await log_channel.send(embed=embed, attachment=file)
                return
            except (hikari.ForbiddenError, hikari.HTTPError, asyncio.TimeoutError):
                return

        if self._queue.get(log_channel.id) is None:
            self._queue[log_channel.id] = []

        self._queue[log_channel.id].append(embed)

    async def freeze_logging(self, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> None:
        """Call to temporarily suspend logging in the given guild. Useful if a log-spammy command is being executed."""
        guild_id = hikari.Snowflake(guild)
        if guild_id not in self._frozen_guilds:
            self._frozen_guilds.append(guild_id)

    async def unfreeze_logging(self, guild: hikari.SnowflakeishOr[hikari.PartialGuild]) -> None:
        """Call to stop suspending the logging in a given guild."""
        await asyncio.sleep(5)  # For any pending actions, kinda crappy solution, but audit logs suck :/
        guild_id = hikari.Snowflake(guild)
        if guild_id in self._frozen_guilds:
            self._frozen_guilds.remove(guild_id)
