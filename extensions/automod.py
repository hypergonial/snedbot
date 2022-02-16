import asyncio
import datetime
import enum
import json
import logging
import typing as t

import hikari
import re
import lightbulb
import miru
import perspective
from etc.settings_static import default_automod_policies, notices
from miru.ext import nav
from models import SnedSlashContext
from models.bot import SnedBot
from utils import helpers
import utils
from utils.ratelimiter import BucketType

logger = logging.getLogger(__name__)

automod = lightbulb.Plugin("Auto-Moderation", include_datastore=True)
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


spam_ratelimiter = utils.RateLimiter(10, 8, bucket=BucketType.MEMBER, wait=False)
punish_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)
attach_spam_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)
link_spam_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)
escalate_prewarn_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)
escalate_ratelimiter = utils.RateLimiter(30, 1, bucket=BucketType.MEMBER, wait=False)


async def get_policies(guild: hikari.SnowflakeishOr[hikari.Guild]) -> None:
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
    message: hikari.Message,
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

    me = automod.app.cache.get_member(message.guild_id, automod.app.user_id)

    offender = offender or message.member

    if not helpers.can_harm(me, offender, permission=required_perms):
        return

    if not original_action and message.channel_id in policies[action.value]["excluded_channels"]:
        return

    if not original_action and message.member.get_top_role().id in policies[action.value]["excluded_roles"]:
        return

    state = policies[action.value]["state"]

    if state == "disabled":
        return

    if not original_action:
        temp_dur = policies[action.value]["temp_dur"]
        should_delete = policies[action.value]["delete"] if action.value != "spam" else False

    else:
        temp_dur = policies[original_action.value]["temp_dur"]
        should_delete = False

    if should_delete:
        await helpers.maybe_delete(message)

    if state == "notice":
        embed = hikari.Embed(
            title="💬 Auto-Moderation Notice",
            description=f"**{offender.display_name}**, please refrain from {notices[action.value]}!",
            color=automod.app.warn_color,
        )
        return await message.respond(embed=embed)

    mod = automod.app.get_plugin("Moderation")

    if not mod:
        return

    if state == "warn":
        return await mod.d.actions.warn(offender, me, f"Warned by auto-moderator for {reason}.")

    elif state == "escalate":
        await escalate_prewarn_ratelimiter.acquire(message)

        if not escalate_prewarn_ratelimiter.is_rate_limited(message):
            embed = hikari.Embed(
                title="💬 Auto-Moderation Notice",
                description=f"**{offender.display_name}**, please refrain from {notices[action.value]}!",
                color=automod.app.warn_color,
            )
            return await message.respond(embed=embed)

        elif escalate_prewarn_ratelimiter.is_rate_limited(message):
            embed = await mod.d.actions.warn(
                offender,
                me,
                f"Warned by auto-moderator for previous offenses ({action.name}).",
            )
            return await message.respond(embed=embed)

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

    elif state == "timeout":

        embed = await mod.d.actions.timeout(
            offender,
            me,
            helpers.utcnow() + datetime.timedelta(minutes=temp_dur),
            reason=f"Timed out by auto-moderator for {reason}.",
        )
        return await message.respond(embed=embed)

    elif state == "kick":
        embed = await mod.d.actions.kick(offender, me, reason=f"Kicked by auto-moderator for {reason}.")
        return await message.respond(embed=embed)

    elif state == "softban":
        embed = await mod.d.actions.ban(offender, me, soft=True, reason=f"Soft-banned by auto-moderator for {reason}.")
        return await message.respond(embed=embed)

    elif state == "tempban":
        embed = await mod.d.actions.ban(
            offender,
            me,
            duration=helpers.utcnow() + datetime.timedelta(minutes=temp_dur),
            reason=f"Temp-banned by auto-moderator for {reason}.",
        )
        return await message.respond(embed=embed)

    elif state == "permaban":
        embed = await mod.d.actions.ban(offender, me, reason=f"Permanently banned by auto-moderator for {reason}.")
        return await message.respond(embed=embed)


@automod.listener(hikari.GuildMessageCreateEvent)
async def scan_messages(event: hikari.GuildMessageCreateEvent) -> None:
    """Scan messages for all possible offences."""

    message = event.message

    if not automod.app.is_alive or not automod.app.db_cache.is_ready:
        return

    if message.guild_id is None:
        return

    if not message.member or message.member.is_bot:
        return

    policies = await get_policies(message.guild_id)

    mentions = sum(user.id != message.author.id and not user.is_bot for user in message.mentions.users)

    if mentions >= policies["mass_mentions"]["count"]:
        return await punish(
            message,
            policies,
            AutomodActionType.MASS_MENTIONS,
            reason=f"spamming {mentions} mentions in a single message",
        )

    await spam_ratelimiter.acquire(message)
    if spam_ratelimiter.is_rate_limited(message):
        return await punish(message, policies, AutomodActionType.SPAM, reason="spam")

    if message.content and len(message.content) > 15:
        chars = [char for char in message.content if char.isalnum()]
        uppers = [char for char in chars if char.isupper()]
        if len(uppers) / len(chars) > 0.6:
            return await punish(
                message,
                policies,
                AutomodActionType.CAPS,
                reason="use of excessive caps",
            )

    if message.content:
        words = message.content.lower().split(" ")

        for word in words:
            if word in policies["bad_words"]["words_list"]:
                return await punish(message, policies, AutomodActionType.BAD_WORDS, "usage of bad words")

        for bad_word in policies["bad_words"]["words_list"]:
            if " " in bad_word and bad_word.lower() in message.content.lower():
                return await punish(message, policies, AutomodActionType.BAD_WORDS, "usage of bad words (expression)")

        for word in policies["bad_words"]["words_list_wildcard"]:
            if word.lower() in message.content.lower():
                return await punish(
                    message, policies, AutomodActionType.BAD_WORDS, reason="usage of bad words (wildcard)"
                )

    invite_regex = re.compile(r"(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?")

    if invite_regex.findall(message.content):
        return await punish(
            message,
            policies,
            AutomodActionType.INVITES,
            reason="posting Discord invites",
        )

    link_regex = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
    link_matches = link_regex.findall(message.content)
    if len(link_matches) > 7:
        return await punish(
            message,
            policies,
            AutomodActionType.LINK_SPAM,
            reason="having too many links in a single message",
        )

    await link_spam_ratelimiter.acquire(message)

    if link_spam_ratelimiter.is_rate_limited(message):
        return await punish(
            message,
            policies,
            AutomodActionType.LINK_SPAM,
            reason="posting links too quickly",
        )

    if message.attachments and len(message.attachments) > 0:
        await attach_spam_ratelimiter.acquire(message)

        if attach_spam_ratelimiter.is_rate_limited(message):
            await punish(
                message, policies, AutomodActionType.ATTACH_SPAM, reason="posting images/attachments too quickly"
            )

    # TODO: Zalgo, Perspective


def load(bot: SnedBot) -> None:
    bot.add_plugin(automod)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(automod)
