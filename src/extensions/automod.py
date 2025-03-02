import datetime
import enum
import logging
import re
import typing as t

import arc
import hikari
import kosu

from src.etc import const
from src.etc.settings_static import notices
from src.models.client import SnedClient, SnedPlugin
from src.models.events import AutoModMessageFlagEvent
from src.utils import helpers

INVITE_REGEX = re.compile(r"(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?")
"""Used to detect and handle Discord invites."""
URL_REGEX = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
"""Used to detect and handle link spam."""
DISCORD_FORMATTING_REGEX = re.compile(r"<\S+>")
"""Remove Discord-specific formatting. Performance is key so some false-positives are acceptable here."""

MEMBER_KEY_FUNC: t.Callable[[hikari.PartialMessage], str] = lambda m: f"{m.author.id if m.author else None}{m.guild_id}"  # noqa: E731

SPAM_RATELIMITER = arc.utils.RateLimiter[hikari.PartialMessage](10, 8, get_key_with=MEMBER_KEY_FUNC)
PUNISH_RATELIMITER = arc.utils.RateLimiter[hikari.PartialMessage](30, 1, get_key_with=MEMBER_KEY_FUNC)
ATTACH_SPAM_RATELIMITER = arc.utils.RateLimiter[hikari.PartialMessage](30, 2, get_key_with=MEMBER_KEY_FUNC)
LINK_SPAM_RATELIMITER = arc.utils.RateLimiter[hikari.PartialMessage](30, 2, get_key_with=MEMBER_KEY_FUNC)
ESCALATE_PREWARN_RATELIMITER = arc.utils.RateLimiter[hikari.PartialMessage](30, 1, get_key_with=MEMBER_KEY_FUNC)
ESCALATE_RATELIMITER = arc.utils.RateLimiter[hikari.PartialMessage](30, 1, get_key_with=MEMBER_KEY_FUNC)

logger = logging.getLogger(__name__)

plugin = SnedPlugin("Auto-Moderation")


class AutomodActionType(enum.Enum):
    INVITES = "invites"
    SPAM = "spam"
    MASS_MENTIONS = "mass_mentions"
    ATTACH_SPAM = "attach_spam"
    LINK_SPAM = "link_spam"
    CAPS = "caps"
    BAD_WORDS = "bad_words"
    ESCALATE = "escalate"
    PERSPECTIVE = "perspective"


class AutoModState(enum.Enum):
    DISABLED = "disabled"
    FLAG = "flag"
    NOTICE = "notice"
    WARN = "warn"
    ESCALATE = "escalate"
    TIMEOUT = "timeout"
    KICK = "kick"
    SOFTBAN = "softban"
    TEMPBAN = "tempban"
    PERMABAN = "permaban"


def can_automod_punish(me: hikari.Member, offender: hikari.Member) -> bool:
    """Determine if automod can punish a member.
    This checks all required permissions and if the member is a cool person or not.

    Parameters
    ----------
    me : hikari.Member
        The bot member.
    offender : hikari.Member
        The member to check.

    Returns
    -------
    bool
        Whether or not the member can be punished.
    """
    required_perms = (
        hikari.Permissions.BAN_MEMBERS
        | hikari.Permissions.MODERATE_MEMBERS
        | hikari.Permissions.MANAGE_MESSAGES
        | hikari.Permissions.KICK_MEMBERS
    )

    assert offender.guild_id is not None

    if offender.id in plugin.client.owner_ids:
        return False  # Hyper is always a good person

    if not helpers.can_harm(me, offender, permission=required_perms):
        return False

    return True


# TODO: Split this
async def punish(
    message: hikari.PartialMessage,
    policies: dict[str, t.Any],
    action: AutomodActionType,
    reason: str,
    offender: hikari.Member | None = None,
    original_action: AutomodActionType | None = None,
    skip_check: bool = False,
) -> None:
    """Execute the appropiate automod punishment on a member.

    Parameters
    ----------
    message : hikari.PartialMessage
        The message that triggered the punishment.
    policies : dict[str, t.Any]
        The guild's auto-moderation policies.
    action : AutomodActionType
        The automod action this punishment should be actioned under.
    reason : str
        The reason for the punishment.
    offender : hikari.Member | None
        The member to punish. If not specified, defaults to the message author.
    original_action : AutomodActionType | None
        The original action that triggered the punishment. Only used for escalate.
    skip_check : bool
        Whether or not to skip the check for if the member can be punished.
    """
    assert message.guild_id is not None
    assert message.author is not hikari.UNDEFINED

    offender = offender or plugin.client.cache.get_member(message.guild_id, message.author.id)
    me = plugin.client.cache.get_member(message.guild_id, plugin.client.user_id)
    assert offender is not None and me is not None

    if not skip_check and not can_automod_punish(me, offender):
        return

    # Check if member has excluded role
    role_ids = [role_id for role_id in offender.role_ids if role_id in policies[action.value]["excluded_roles"]]
    if not original_action and role_ids:
        return

    state = policies[action.value]["state"]

    if state == AutoModState.DISABLED.value:
        return

    # States that silence the user and their repetition is undesirable
    silencers = [
        AutoModState.TIMEOUT.value,
        AutoModState.KICK.value,
        AutoModState.TEMPBAN.value,
        AutoModState.SOFTBAN.value,
        AutoModState.PERMABAN.value,
    ]

    if policies[AutoModState.ESCALATE.value]["state"] in silencers:
        silencers.append(AutoModState.ESCALATE.value)

    if state in silencers:
        try:
            await PUNISH_RATELIMITER.acquire(message, wait=False)
        except arc.utils.RateLimiterExhaustedError:
            return

    if not original_action:
        temp_dur = policies[action.value]["temp_dur"]
        should_delete = policies[action.value]["delete"] if action.value != "spam" else False

    else:
        temp_dur = policies[original_action.value]["temp_dur"]
        should_delete = False

    if should_delete:
        await helpers.maybe_delete(message)

    if state == AutoModState.FLAG.value:
        return await plugin.client.app.dispatch(
            AutoModMessageFlagEvent(
                plugin.client.app,
                message,
                offender,
                message.guild_id,
                f"Message flagged by auto-moderator for {reason}.",
            )
        )

    if state == AutoModState.NOTICE.value:
        await message.respond(
            content=offender.mention,
            embed=hikari.Embed(
                title="💬 Auto-Moderation Notice",
                description=f"**{offender.display_name}**, please refrain from {notices[action.value]}!",
                color=const.WARN_COLOR,
            ),
            user_mentions=True,
        )
        return await plugin.client.app.dispatch(
            AutoModMessageFlagEvent(
                plugin.client.app,
                message,
                offender,
                message.guild_id,
                f"Message flagged by auto-moderator for {reason}.",
            )
        )

    if state == AutoModState.WARN.value:
        embed = await plugin.client.mod.warn(offender, me, f"Warned by auto-moderator for {reason}.")
        await message.respond(embed=embed)
        return

    elif state == AutoModState.ESCALATE.value:
        try:
            # Check if the user has been warned before
            await ESCALATE_PREWARN_RATELIMITER.acquire(message, wait=False)
            # If not, issue a notice
            await message.respond(
                content=offender.mention,
                embed=hikari.Embed(
                    title="💬 Auto-Moderation Notice",
                    description=f"**{offender.display_name}**, please refrain from {notices[action.value]}!",
                    color=const.WARN_COLOR,
                ),
                user_mentions=True,
            )
            return await plugin.client.app.dispatch(
                AutoModMessageFlagEvent(
                    plugin.client.app,
                    message,
                    offender,
                    message.guild_id,
                    f"Message flagged by auto-moderator for {reason} ({action.name}).",
                )
            )
        except hikari.RateLimitTooLongError:
            # If yes, then check if we should escalate
            try:
                await ESCALATE_RATELIMITER.acquire(message, wait=False)
                # If not, issue a warning
                embed = await plugin.client.mod.warn(
                    offender,
                    me,
                    f"Warned by auto-moderator for previous offenses ({action.name}).",
                )
                await message.respond(embed=embed)
                return
            except arc.utils.RateLimiterExhaustedError:
                # Escalate to a full punishment
                return await punish(
                    message=message,
                    policies=policies,
                    action=AutomodActionType.ESCALATE,
                    reason=f"previous offenses ({action.name})",
                    original_action=action,
                    offender=offender,
                )

    elif state == AutoModState.TIMEOUT.value:
        embed = await plugin.client.mod.timeout(
            offender,
            me,
            helpers.utcnow() + datetime.timedelta(minutes=temp_dur),
            reason=f"Timed out by auto-moderator for {reason}.",
        )
        await message.respond(embed=embed)
        return

    elif state == AutoModState.KICK.value:
        embed = await plugin.client.mod.kick(offender, me, reason=f"Kicked by auto-moderator for {reason}.")
        await message.respond(embed=embed)
        return

    elif state == AutoModState.SOFTBAN.value:
        embed = await plugin.client.mod.ban(
            offender, me, soft=True, reason=f"Soft-banned by auto-moderator for {reason}.", days_to_delete=1
        )
        await message.respond(embed=embed)
        return

    elif state == AutoModState.TEMPBAN.value:
        embed = await plugin.client.mod.ban(
            offender,
            me,
            duration=helpers.utcnow() + datetime.timedelta(minutes=temp_dur),
            reason=f"Temp-banned by auto-moderator for {reason}.",
        )
        await message.respond(embed=embed)
        return

    elif state == AutoModState.PERMABAN.value:
        embed = await plugin.client.mod.ban(offender, me, reason=f"Permanently banned by auto-moderator for {reason}.")
        await message.respond(embed=embed)
        return


async def detect_mass_mentions(message: hikari.PartialMessage, policies: dict[str, t.Any]) -> bool:
    """Detect mass mentions in a message.

    Parameters
    ----------
    message : hikari.PartialMessage
        The message to check.
    policies : dict[str, t.Any]
        The guild's auto-moderation policies.

    Returns
    -------
    bool
    Whether or not the analysis should proceed to the next check.
    """
    if policies["mass_mentions"]["state"] != AutoModState.DISABLED.value and message.user_mentions:
        assert message.author
        mentions = sum(user.id != message.author.id and not user.is_bot for user in message.user_mentions.values())

        if mentions >= policies["mass_mentions"]["count"]:
            await punish(
                message,
                policies,
                AutomodActionType.MASS_MENTIONS,
                reason=f"spamming {mentions}/{policies['mass_mentions']['count']} mentions in a single message",
            )
            return False
    return True


async def detect_spam(message: hikari.PartialMessage, policies: dict[str, t.Any]) -> bool:
    """Detect spam in a message.

    Parameters
    ----------
    message : hikari.PartialMessage
        The message to check.
    policies : dict[str, t.Any]
        The guild's auto-moderation policies.

    Returns
    -------
    bool
        Whether or not the analysis should proceed to the next check.
    """
    if policies["spam"]["state"] == AutoModState.DISABLED.value:
        return True

    try:
        await SPAM_RATELIMITER.acquire(message, wait=False)
    except arc.utils.RateLimiterExhaustedError:
        await punish(message, policies, AutomodActionType.SPAM, reason="spam")
        return False
    return True


async def detect_attach_spam(message: hikari.PartialMessage, policies: dict[str, t.Any]) -> bool:
    """Detect attachment spam in a message.

    Parameters
    ----------
    message : hikari.PartialMessage
        The message to check.
    policies : dict[str, t.Any]
        The guild's auto-moderation policies.

    Returns
    -------
    bool
        Whether or not the analysis should proceed to the next check.
    """
    if policies["attach_spam"]["state"] == AutoModState.DISABLED.value or not message.attachments:
        return True

    try:
        await ATTACH_SPAM_RATELIMITER.acquire(message, wait=False)
    except arc.utils.RateLimiterExhaustedError:
        await punish(message, policies, AutomodActionType.ATTACH_SPAM, reason="posting images/attachments too quickly")
        return False
    return True


async def detect_bad_words(message: hikari.PartialMessage, policies: dict[str, t.Any]) -> bool:
    """Detect bad words in a message.

    Parameters
    ----------
    message : hikari.PartialMessage
        The message to check.
    policies : dict[str, t.Any]
        The guild's auto-moderation policies.

    Returns
    -------
    bool
        Whether or not the analysis should proceed to the next check.
    """
    if not message.content:
        return True

    if policies["bad_words"]["state"] != AutoModState.DISABLED.value:
        for word in message.content.lower().split(" "):
            if word in policies["bad_words"]["words_list"]:
                await punish(message, policies, AutomodActionType.BAD_WORDS, "usage of bad words")
                return False

        for bad_word in policies["bad_words"]["words_list"]:
            if " " in bad_word and bad_word.lower() in message.content.lower():
                await punish(message, policies, AutomodActionType.BAD_WORDS, "usage of bad words (expression)")
                return False

        for bad_word in policies["bad_words"]["words_list_wildcard"]:
            if bad_word.lower() in message.content.lower():
                await punish(message, policies, AutomodActionType.BAD_WORDS, reason="usage of bad words (wildcard)")
                return False
    return True


async def detect_caps(message: hikari.PartialMessage, policies: dict[str, t.Any]) -> bool:
    """Detect excessive caps in a message.

    Parameters
    ----------
    message : hikari.PartialMessage
        The message to check.
    policies : dict[str, t.Any]
        The guild's auto-moderation policies.

    Returns
    -------
    bool
        Whether or not the analysis should proceed to the next check.
    """
    if not message.content:
        return True

    if policies["caps"]["state"] != AutoModState.DISABLED.value and len(message.content) > 15:
        chars = [char for char in message.content if char.isalnum()]
        uppers = [char for char in chars if char.isupper() and char.isalnum()]
        if chars and len(uppers) / len(chars) > 0.6:
            await punish(
                message,
                policies,
                AutomodActionType.CAPS,
                reason="use of excessive caps",
            )
            return False
    return True


async def detect_link_spam(message: hikari.PartialMessage, policies: dict[str, t.Any]) -> bool:
    """Detect link spam in a message.

    Parameters
    ----------
    message : hikari.PartialMessage
        The message to check.
    policies : dict[str, t.Any]
        The guild's auto-moderation policies.

    Returns
    -------
    bool
        Whether or not the analysis should proceed to the next check.
    """
    if not message.content or policies["link_spam"]["state"] == AutoModState.DISABLED.value:
        return True

    link_matches = URL_REGEX.findall(message.content)
    if len(link_matches) > 7:
        await punish(
            message,
            policies,
            AutomodActionType.LINK_SPAM,
            reason="having too many links in a single message",
        )
        return False

    if link_matches:
        try:
            await LINK_SPAM_RATELIMITER.acquire(message, wait=False)
        except arc.utils.RateLimiterExhaustedError:
            await punish(
                message,
                policies,
                AutomodActionType.LINK_SPAM,
                reason="posting links too quickly",
            )
            return False
    return True


async def detect_invites(message: hikari.PartialMessage, policies: dict[str, t.Any]) -> bool:
    """Detect Discord invites in a message.

    Parameters
    ----------
    message : hikari.PartialMessage
        The message to check.
    policies : dict[str, t.Any]
        The guild's auto-moderation policies.

    Returns
    -------
    bool
        Whether or not the analysis should proceed to the next check.
    """
    if not message.content:
        return True

    if policies["invites"]["state"] != AutoModState.DISABLED.value and INVITE_REGEX.findall(message.content):
        await punish(
            message,
            policies,
            AutomodActionType.INVITES,
            reason="posting Discord invites",
        )
        return False
    return True


async def detect_perspective(message: hikari.PartialMessage, policies: dict[str, t.Any]) -> bool:
    """Detect toxicity in a message using Perspective.

    Parameters
    ----------
    message : hikari.PartialMessage
        The message to check.
    policies : dict[str, t.Any]
        The guild's auto-moderation policies.

    Returns
    -------
    bool
        Whether or not the analysis should proceed to the next check.
    """
    if not message.content:
        return True

    assert message.guild_id and message.member

    if policies["perspective"]["state"] != AutoModState.DISABLED.value:
        me = plugin.client.cache.get_member(message.guild_id, plugin.client.user_id)
        assert me is not None

        # This is a pretty expensive check so we'll only do it if we have to
        if not can_automod_punish(me, message.member):
            return True

        persp_attribs = [
            kosu.Attribute(kosu.AttributeName.TOXICITY),
            kosu.Attribute(kosu.AttributeName.SEVERE_TOXICITY),
            kosu.Attribute(kosu.AttributeName.PROFANITY),
            kosu.Attribute(kosu.AttributeName.INSULT),
            kosu.Attribute(kosu.AttributeName.THREAT),
        ]

        # Remove custom emojis, mentions, and other Discord-specific formatting
        analysis_str = DISCORD_FORMATTING_REGEX.sub("", message.content).strip()

        if len(analysis_str) < 3:
            return True

        try:
            resp: kosu.AnalysisResponse = await plugin.client.perspective.analyze(message.content, persp_attribs)
        except kosu.PerspectiveException as e:
            logger.debug(f"Perspective failed to analyze a message: {e}")
        else:
            scores = {score.name.name: score.summary.value for score in resp.attribute_scores}

            for score, value in scores.items():
                if value > policies["perspective"]["persp_bounds"][score]:
                    await punish(
                        message,
                        policies,
                        AutomodActionType.PERSPECTIVE,
                        reason=f"toxic content detected by Perspective ({score.replace('_', ' ').lower()}: {round(value * 100)}%)",
                        skip_check=True,
                    )
                    return False
    return True


@plugin.listen()
async def scan_messages(event: hikari.GuildMessageCreateEvent | hikari.GuildMessageUpdateEvent) -> None:
    """Scan messages for all possible offences."""
    message = event.message

    if not message.author:
        # Probably a partial update, ignore it
        return

    if not plugin.client.is_started or not plugin.client.db_cache.is_ready:
        return

    if message.guild_id is None:
        return

    if not message.member or message.member.is_bot:
        return

    policies = await plugin.client.mod.get_automod_policies(message.guild_id)

    if isinstance(event, hikari.GuildMessageUpdateEvent):
        all(
            (
                await detect_mass_mentions(message, policies),
                await detect_bad_words(message, policies),
                await detect_caps(message, policies),
                await detect_invites(message, policies),
                await detect_perspective(message, policies),
            )
        )
    else:
        all(
            (
                await detect_mass_mentions(message, policies),
                await detect_spam(message, policies),
                await detect_attach_spam(message, policies),
                await detect_bad_words(message, policies),
                await detect_caps(message, policies),
                await detect_invites(message, policies),
                await detect_link_spam(message, policies),
                await detect_perspective(message, policies),
            )
        )


@arc.loader
def load(client: SnedClient) -> None:
    client.add_plugin(plugin)


@arc.unloader
def unload(client: SnedClient) -> None:
    client.remove_plugin(plugin)


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
