import typing as t

import hikari

if t.TYPE_CHECKING:
    from models.bot import SnedBot

import logging

logger = logging.getLogger(__name__)


class AuditLogCache:
    """A cache for audit log entries categorized by guild and entry type.

    Parameters
    ----------
    bot: SnedBot
        The bot instance.
    capacity: int
        The maximum number of entries to store per guild and event type. If the number
        of entries exceed this number, the oldest entries will be discarded.
    """

    def __init__(self, bot: SnedBot, capacity: int = 10) -> None:
        self._cache: t.Dict[hikari.Snowflake, t.Dict[hikari.AuditLogEventType, t.List[hikari.AuditLogEntry]]] = {}
        self._capacity = capacity
        self._bot = bot

    async def start(self) -> None:
        """Start the audit log cache listener."""
        self._bot.event_manager.subscribe(hikari.Event, self._listen)

    async def stop(self) -> None:
        """Stop the audit log cache listener."""
        self._bot.event_manager.unsubscribe(hikari.Event, self._listen)
        self._cache = {}

    async def _listen(self, event: hikari.Event) -> None:
        """Listen for audit log events."""
        raise NotImplementedError("AuditLogCache listener not implemented!")
        # TODO: do impl:
        # self.add(event.guild_id, event.entry)

    def get(
        self, guild: hikari.SnowflakeishOr[hikari.PartialGuild], action_type: hikari.AuditLogEventType
    ) -> t.List[hikari.AuditLogEntry]:
        """Get all audit log entries for a guild and event type.

        Parameters
        ----------
        guild: hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild or it's ID.
        action_type: hikari.AuditLogEventType
            The event type.

        Returns
        -------
        List[hikari.AuditLogEntry]
            The audit log entries.
        """
        return self._cache.get(hikari.Snowflake(guild), {}).get(action_type, [])

    def get_first_by(
        self,
        guild: hikari.SnowflakeishOr[hikari.PartialGuild],
        action_type: hikari.AuditLogEventType,
        predicate: t.Callable[[hikari.AuditLogEntry], bool],
    ) -> t.Optional[hikari.AuditLogEntry]:
        """Get the first audit log entry that matches a predicate.

        Parameters
        ----------
        guild: hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild or it's ID.
        action_type: hikari.AuditLogEventType
            The event type.
        predicate: Callable[[hikari.AuditLogEntry], bool]
            The predicate to match.

        Returns
        -------
        Optional[hikari.AuditLogEntry]
            The first audit log entry that matches the predicate, or None if no entry matches.
        """
        for entry in self.get(guild, action_type):
            if predicate(entry):
                return entry

        return None

    def add(self, guild: hikari.SnowflakeishOr[hikari.PartialGuild], entry: hikari.AuditLogEntry) -> None:
        """Add a new audit log entry to the cache.

        Parameters
        ----------
        guild: hikari.SnowflakeishOr[hikari.PartialGuild]
            The guild or it's ID.
        entry: hikari.AuditLogEntry
            The audit log entry to add.
        """
        if not isinstance(entry.action_type, hikari.AuditLogEventType):
            logger.warning(f"Unrecognized audit log entry type found: {entry.action_type}")
            return

        guild_id = hikari.Snowflake(guild)

        if guild_id not in self._cache:
            self._cache[guild_id] = {}

        if entry.action_type not in self._cache[guild_id]:
            self._cache[guild_id][entry.action_type] = []

        # Remove the oldest entry if the cache is full
        if len(self._cache[guild_id][entry.action_type]) >= self._capacity:
            self._cache[guild_id][entry.action_type].pop(0)

        self._cache[guild_id][entry.action_type].append(entry)
