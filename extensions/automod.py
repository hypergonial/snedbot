import datetime
import enum
import json
import logging
import re
import typing as t

import hikari
import kosu
import lightbulb

import utils
from etc import const
from etc.settings_static import default_automod_policies, notices
from models.bot import SnedBot
from models.events import AutoModMessageFlagEvent
from models.plugin import SnedPlugin
from utils import helpers
from utils.ratelimiter import BucketType

logger = logging.getLogger(__name__)

automod = SnedPlugin("Auto-Moderation", include_datastore=True)
automod.d.actions = lightbulb.utils.DataStore()


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


spam_ratelimiter = utils.RateLimiter(10, 8, bucket=BucketType.MEMBER, wait=False)
punish_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)
attach_spam_ratelimiter = utils.RateLimiter(30, 2, bucket=BucketType.MEMBER, wait=False)
link_spam_ratelimiter = utils.RateLimiter(30, 2, bucket=BucketType.MEMBER, wait=False)
escalate_prewarn_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)
escalate_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)


async def get_policies(guild: hikari.SnowflakeishOr[hikari.Guild]) -> t.Dict[str, t.Any]:
    """Return auto-moderation policies for the specified guild."""

    guild_id = hikari.Snowflake(guild)

    records = await automod.app.db_cache.get(table="mod_config", guild_id=guild_id)

    policies = json.loads(records[0]["automod_policies"]) if records else default_automod_policies

    for key in default_automod_policies.keys():
        if key not in policies:
            policies[key] = default_automod_policies[key]

        for nested_key in default_automod_policies[key].keys():
            if nested_key not in policies[key]:
                policies[key][nested_key] = default_automod_policies[key][nested_key]

    invalid = []
    for key in policies.keys():
        if key not in default_automod_policies.keys():
            invalid.append(key)

    for key in invalid:
        policies.pop(key)

    return policies


automod.d.actions.get_policies = get_policies


async def punish(
    message: hikari.PartialMessage,
    policies: t.Dict[str, t.Any],
    action: AutomodActionType,
    reason: str,
    offender: t.Optional[hikari.Member] = None,
    original_action: t.Optional[AutomodActionType] = None,
) -> None:

    required_perms = (
        hikari.Permissions.BAN_MEMBERS
        | hikari.Permissions.MODERATE_MEMBERS
        | hikari.Permissions.MANAGE_MESSAGES
        | hikari.Permissions.KICK_MEMBERS
    )

    assert message.guild_id is not None

    me = automod.app.cache.get_member(message.guild_id, automod.app.user_id)
    assert me is not None

    assert message.author is not hikari.UNDEFINED
    offender = offender or automod.app.cache.get_member(message.guild_id, message.author.id)
    assert offender is not None

    if offender.id in automod.app.owner_ids:
        return  # Hyper is always a good person

    if not helpers.can_harm(me, offender, permission=required_perms):
        return

    # Check if channel is excluded
    if not original_action and message.channel_id in policies[action.value]["excluded_channels"]:
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
        await punish_ratelimiter.acquire(message)

        if punish_ratelimiter.is_rate_limited(message):
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
        return await automod.app.dispatch(
            AutoModMessageFlagEvent(
                automod.app, message, offender, message.guild_id, f"Message flagged by auto-moderator for {reason}."
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
        return await automod.app.dispatch(
            AutoModMessageFlagEvent(
                automod.app, message, offender, message.guild_id, f"Message flagged by auto-moderator for {reason}."
            )
        )

    if state == AutoModState.WARN.value:
        embed = await automod.app.mod.warn(offender, me, f"Warned by auto-moderator for {reason}.")
        await message.respond(embed=embed)
        return

    elif state == AutoModState.ESCALATE.value:
        await escalate_prewarn_ratelimiter.acquire(message)

        if not escalate_prewarn_ratelimiter.is_rate_limited(message):
            await message.respond(
                content=offender.mention,
                embed=hikari.Embed(
                    title="💬 Auto-Moderation Notice",
                    description=f"**{offender.display_name}**, please refrain from {notices[action.value]}!",
                    color=const.WARN_COLOR,
                ),
                user_mentions=True,
            )
            return await automod.app.dispatch(
                AutoModMessageFlagEvent(
                    automod.app,
                    message,
                    offender,
                    message.guild_id,
                    f"Message flagged by auto-moderator for {reason} ({action.name}).",
                )
            )

        elif escalate_prewarn_ratelimiter.is_rate_limited(message):
            embed = await automod.app.mod.warn(
                offender,
                me,
                f"Warned by auto-moderator for previous offenses ({action.name}).",
            )
            await message.respond(embed=embed)
            return

        else:
            await escalate_ratelimiter.acquire(message)
            if escalate_ratelimiter.is_rate_limited(message):
                return await punish(
                    message=message,
                    policies=policies,
                    action=AutomodActionType.ESCALATE,
                    reason=f"previous offenses ({action.name})",
                    original_action=action,
                    offender=offender,
                )

    elif state == AutoModState.TIMEOUT.value:

        embed = await automod.app.mod.timeout(
            offender,
            me,
            helpers.utcnow() + datetime.timedelta(minutes=temp_dur),
            reason=f"Timed out by auto-moderator for {reason}.",
        )
        await message.respond(embed=embed)
        return

    elif state == AutoModState.KICK.value:
        embed = await automod.app.mod.kick(offender, me, reason=f"Kicked by auto-moderator for {reason}.")
        await message.respond(embed=embed)
        return

    elif state == AutoModState.SOFTBAN.value:
        embed = await automod.app.mod.ban(
            offender, me, soft=True, reason=f"Soft-banned by auto-moderator for {reason}.", days_to_delete=1
        )
        await message.respond(embed=embed)
        return

    elif state == AutoModState.TEMPBAN.value:
        embed = await automod.app.mod.ban(
            offender,
            me,
            duration=helpers.utcnow() + datetime.timedelta(minutes=temp_dur),
            reason=f"Temp-banned by auto-moderator for {reason}.",
        )
        await message.respond(embed=embed)
        return

    elif state == AutoModState.PERMABAN.value:
        embed = await automod.app.mod.ban(offender, me, reason=f"Permanently banned by auto-moderator for {reason}.")
        await message.respond(embed=embed)
        return


@automod.listener(hikari.GuildMessageCreateEvent, bind=True)
@automod.listener(hikari.GuildMessageUpdateEvent, bind=True)
async def scan_messages(
    plugin: SnedPlugin, event: t.Union[hikari.GuildMessageCreateEvent, hikari.GuildMessageUpdateEvent]
) -> None:
    """Scan messages for all possible offences."""

    message = event.message

    if not message.author:
        # Probably a partial update, ignore it
        return

    if not plugin.app.is_started or not plugin.app.db_cache.is_ready:
        return

    if message.guild_id is None:
        return

    if not message.member or message.member.is_bot:
        return

    policies = await get_policies(guild=message.guild_id)

    if policies["mass_mentions"]["state"] != AutoModState.DISABLED.value and message.user_mentions:
        assert message.author
        mentions = sum(user.id != message.author.id and not user.is_bot for user in message.user_mentions.values())

        if mentions >= policies["mass_mentions"]["count"]:
            return await punish(
                message,
                policies,
                AutomodActionType.MASS_MENTIONS,
                reason=f"spamming {mentions}/{policies['mass_mentions']['count']} mentions in a single message",
            )

    await spam_ratelimiter.acquire(message)
    if policies["spam"]["state"] != AutoModState.DISABLED.value and spam_ratelimiter.is_rate_limited(message):
        return await punish(message, policies, AutomodActionType.SPAM, reason="spam")

    if isinstance(event, hikari.GuildMessageCreateEvent):
        if policies["attach_spam"]["state"] != AutoModState.DISABLED.value and message.attachments:
            await attach_spam_ratelimiter.acquire(message)

            if attach_spam_ratelimiter.is_rate_limited(message):
                await punish(
                    message, policies, AutomodActionType.ATTACH_SPAM, reason="posting images/attachments too quickly"
                )

    # Everything that requires message content follows below
    if not message.content:
        return

    if policies["caps"]["state"] != AutoModState.DISABLED.value and len(message.content) > 15:
        chars = [char for char in message.content if char.isalnum()]
        uppers = [char for char in chars if char.isupper() and char.isalnum()]
        if chars and len(uppers) / len(chars) > 0.6:
            return await punish(
                message,
                policies,
                AutomodActionType.CAPS,
                reason="use of excessive caps",
            )

    if policies["bad_words"]["state"] != AutoModState.DISABLED.value:
        for word in message.content.lower().split(" "):
            if word in policies["bad_words"]["words_list"]:
                return await punish(message, policies, AutomodActionType.BAD_WORDS, "usage of bad words")

        for bad_word in policies["bad_words"]["words_list"]:
            if " " in bad_word and bad_word.lower() in message.content.lower():
                return await punish(message, policies, AutomodActionType.BAD_WORDS, "usage of bad words (expression)")

        for bad_word in policies["bad_words"]["words_list_wildcard"]:
            if bad_word.lower() in message.content.lower():
                return await punish(
                    message, policies, AutomodActionType.BAD_WORDS, reason="usage of bad words (wildcard)"
                )

    if policies["invites"]["state"] != AutoModState.DISABLED.value:
        invite_regex = re.compile(r"(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?")

        if invite_regex.findall(message.content):
            return await punish(
                message,
                policies,
                AutomodActionType.INVITES,
                reason="posting Discord invites",
            )

    if isinstance(event, hikari.GuildMessageCreateEvent):
        if policies["link_spam"]["state"] != AutoModState.DISABLED.value:
            link_regex = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
            link_matches = link_regex.findall(message.content)
            if len(link_matches) > 7:
                return await punish(
                    message,
                    policies,
                    AutomodActionType.LINK_SPAM,
                    reason="having too many links in a single message",
                )

            if not link_matches:
                return

            await link_spam_ratelimiter.acquire(message)

            if link_spam_ratelimiter.is_rate_limited(message):
                return await punish(
                    message,
                    policies,
                    AutomodActionType.LINK_SPAM,
                    reason="posting links too quickly",
                )

    if policies["perspective"]["state"] != AutoModState.DISABLED.value:
        persp_attribs = [
            kosu.Attribute(kosu.AttributeName.TOXICITY),
            kosu.Attribute(kosu.AttributeName.SEVERE_TOXICITY),
            kosu.Attribute(kosu.AttributeName.PROFANITY),
            kosu.Attribute(kosu.AttributeName.INSULT),
            kosu.Attribute(kosu.AttributeName.THREAT),
        ]
        try:
            assert plugin.app.perspective is not None
            resp: kosu.AnalysisResponse = await plugin.app.perspective.analyze(message.content, persp_attribs)
        except kosu.PerspectiveException as e:
            logger.warning(f"Perspective failed to analyze a message: {str(e)}")
            return
        scores = {score.name.name: score.summary.value for score in resp.attribute_scores}

        for score, value in scores.items():
            if value > policies["perspective"]["persp_bounds"][score]:
                return await punish(
                    message,
                    policies,
                    AutomodActionType.PERSPECTIVE,
                    reason=f"toxic content detected by Perspective ({score.replace('_', ' ').lower()}: {round(value*100)}%)",
                )


def load(bot: SnedBot) -> None:
    bot.add_plugin(automod)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(automod)


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
