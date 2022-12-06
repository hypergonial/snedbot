import datetime
import logging
import re
import typing as t

import hikari
import lightbulb
import miru

import models
from etc import const
from models import errors
from models.bot import SnedBot
from models.checks import (
    bot_has_permissions,
    has_permissions,
    is_above_target,
    is_invoker_above_target,
)
from models.context import SnedSlashContext, SnedUserContext
from models.db_user import DatabaseUser
from models.events import MassBanEvent
from models.mod_actions import ModerationFlags
from models.plugin import SnedPlugin
from utils import helpers

logger = logging.getLogger(__name__)

mod = SnedPlugin("Moderation", include_datastore=True)


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.MANAGE_GUILD, dm_enabled=False)
@lightbulb.option("user", "The user to show information about.", type=hikari.User)
@lightbulb.command("whois", "Show user information about the specified user.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def whois(ctx: SnedSlashContext, user: hikari.User) -> None:
    embed = await helpers.get_userinfo(ctx, user)
    await ctx.mod_respond(embed=embed)


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.MANAGE_GUILD, dm_enabled=False)
@lightbulb.command("Show Userinfo", "Show user information about the target user.", pass_options=True)
@lightbulb.implements(lightbulb.UserCommand)
async def whois_user_command(ctx: SnedUserContext, target: hikari.User) -> None:
    embed = await helpers.get_userinfo(ctx, target)
    await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.MANAGE_ROLES, dm_enabled=False)
@lightbulb.command("role", "Manage roles using commands.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def role_group(ctx: SnedSlashContext) -> None:
    pass


@role_group.child
@lightbulb.option("role", "The role to add", type=hikari.Role)
@lightbulb.option("user", "The user to add the role to", type=hikari.Member)
@lightbulb.command("add", "Add a role to the target user.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def role_add(ctx: SnedSlashContext, user: hikari.Member, role: hikari.Role) -> None:
    helpers.is_member(user)
    assert ctx.guild_id and ctx.member

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
    assert me

    if role.is_managed or role.is_premium_subscriber_role or role.id == ctx.guild_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Role is managed",
                description="This role is managed by another integration and cannot be assigned manually to a user.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if role.id in user.role_ids:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Role already assigned",
                description="This user already has this role.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    bot_top_role = me.get_top_role()
    if not bot_top_role or bot_top_role.position <= role.position:
        raise errors.BotRoleHierarchyError("Target role is higher than bot's highest role.")

    author_top_role = ctx.member.get_top_role()
    guild = ctx.get_guild()
    if (not author_top_role or author_top_role.position <= role.position) and (
        not guild or guild.owner_id != ctx.member.id
    ):
        raise errors.RoleHierarchyError("Target role is higher than your highest role.")

    await ctx.app.rest.add_role_to_member(
        ctx.guild_id, user, role, reason=f"{ctx.member} ({ctx.member.id}): Added role via Sned"
    )
    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Role added", description=f"Added role {role.mention} to `{user}`.", color=const.EMBED_GREEN
        )
    )


@role_group.child
@lightbulb.option("role", "The role to remove", type=hikari.Role)
@lightbulb.option("user", "The user to remove the role from", type=hikari.Member)
@lightbulb.command("remove", "Remove a role from the target user.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def role_del(ctx: SnedSlashContext, user: hikari.Member, role: hikari.Role) -> None:
    helpers.is_member(user)
    assert ctx.guild_id and ctx.member

    me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
    assert me

    if role.is_managed or role.is_premium_subscriber_role or role.id == ctx.guild_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Role is managed",
                description="This role is managed by another integration and cannot be assigned manually to a user.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if role.id not in user.role_ids:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Role not assigned",
                description="This user does not have this role.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    bot_top_role = me.get_top_role()
    if not bot_top_role or bot_top_role.position <= role.position:
        raise errors.BotRoleHierarchyError("Target role is higher than bot's highest role.")

    author_top_role = ctx.member.get_top_role()
    guild = ctx.get_guild()
    if (not author_top_role or author_top_role.position <= role.position) and (
        not guild or guild.owner_id != ctx.member.id
    ):
        raise errors.RoleHierarchyError("Target role is higher than your highest role.")

    await ctx.app.rest.remove_role_from_member(
        ctx.guild_id, user, role, reason=f"{ctx.member} ({ctx.member.id}): Removed role via Sned"
    )
    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Role removed", description=f"Removed role {role.mention} from `{user}`.", color=const.EMBED_GREEN
        )
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.MANAGE_MESSAGES, dm_enabled=False)
@lightbulb.add_cooldown(20, 1, lightbulb.ChannelBucket)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.MANAGE_MESSAGES, hikari.Permissions.READ_MESSAGE_HISTORY),
)
@lightbulb.option("user", "Only delete messages authored by this user.", type=hikari.User, required=False)
@lightbulb.option("regex", "Only delete messages that match with the regular expression.", required=False)
@lightbulb.option("embeds", "Only delete messages that contain embeds.", type=bool, required=False)
@lightbulb.option("links", "Only delete messages that contain links.", type=bool, required=False)
@lightbulb.option("invites", "Only delete messages that contain Discord invites.", type=bool, required=False)
@lightbulb.option("attachments", "Only delete messages that contain files & images.", type=bool, required=False)
@lightbulb.option("onlytext", "Only delete messages that exclusively contain text.", type=bool, required=False)
@lightbulb.option("notext", "Only delete messages that do not contain text.", type=bool, required=False)
@lightbulb.option("endswith", "Only delete messages that end with the specified text.", required=False)
@lightbulb.option("startswith", "Only delete messages that start with the specified text.", required=False)
@lightbulb.option("count", "The amount of messages to delete.", type=int, min_value=1, max_value=100)
@lightbulb.command("purge", "Purge multiple messages in this channel.")
@lightbulb.implements(lightbulb.SlashCommand)
async def purge(ctx: SnedSlashContext) -> None:

    channel = ctx.get_channel() or await ctx.app.rest.fetch_channel(ctx.channel_id)
    assert isinstance(channel, hikari.TextableGuildChannel)

    predicates = [
        # Ignore deferred typing indicator so it doesn't get deleted lmfao
        lambda message: not (hikari.MessageFlag.LOADING & message.flags)
    ]

    if ctx.options.regex:
        try:
            regex = re.compile(ctx.options.regex)
        except re.error as error:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Invalid regex passed",
                    description=f"Failed parsing regex: ```{str(error)}```",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

            assert ctx.invoked is not None and ctx.invoked.cooldown_manager is not None
            return await ctx.invoked.cooldown_manager.reset_cooldown(ctx)
        else:
            predicates.append(lambda message, regex=regex: regex.match(message.content) if message.content else False)

    if ctx.options.startswith:
        predicates.append(
            lambda message: message.content.startswith(ctx.options.startswith) if message.content else False
        )

    if ctx.options.endswith:
        predicates.append(lambda message: message.content.endswith(ctx.options.endswith) if message.content else False)

    if ctx.options.notext:
        predicates.append(lambda message: not message.content)

    if ctx.options.onlytext:
        predicates.append(lambda message: message.content and not message.attachments and not message.embeds)

    if ctx.options.attachments:
        predicates.append(lambda message: bool(message.attachments))

    if ctx.options.invites:
        predicates.append(
            lambda message: helpers.is_invite(message.content, fullmatch=False) if message.content else False
        )

    if ctx.options.links:
        predicates.append(
            lambda message: helpers.is_url(message.content, fullmatch=False) if message.content else False
        )

    if ctx.options.embeds:
        predicates.append(lambda message: bool(message.embeds))

    if ctx.options.user:
        predicates.append(lambda message: message.author.id == ctx.options.user.id)

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    messages = (
        await ctx.app.rest.fetch_messages(channel)
        .take_until(lambda m: (helpers.utcnow() - datetime.timedelta(days=14)) > m.created_at)
        .filter(*predicates)
        .limit(ctx.options.count)
    )

    if messages:
        try:
            await ctx.app.rest.delete_messages(channel, messages)
            embed = hikari.Embed(
                title="🗑️ Messages purged",
                description=f"**{len(messages)}** messages have been deleted.",
                color=const.EMBED_GREEN,
            )

        except hikari.BulkDeleteError as error:
            embed = hikari.Embed(
                title="🗑️ Messages purged",
                description=f"Only **{len(error.messages_deleted)}/{len(messages)}** messages have been deleted due to an error.",
                color=const.WARN_COLOR,
            )
            raise error
    else:
        embed = hikari.Embed(
            title="🗑️ Not found",
            description=f"No messages matched the specified criteria from the past two weeks!",
            color=const.ERROR_COLOR,
        )

    await ctx.mod_respond(embed=embed)


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.MANAGE_NICKNAMES, dm_enabled=False)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.MANAGE_NICKNAMES),
    is_invoker_above_target,
    is_above_target,
)
@lightbulb.option(
    "strict",
    "Defaults to True. If enabled, uses stricter filtering and may filter out certain valid letters.",
    type=bool,
    required=False,
)
@lightbulb.option("user", "The user who's nickname should be deobfuscated.", type=hikari.Member, required=True)
@lightbulb.command("deobfuscate", "Deobfuscate a user's nickname.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def deobfuscate_nick(ctx: SnedSlashContext, user: hikari.Member, strict: bool = True) -> None:
    helpers.is_member(user)

    new_nick = helpers.normalize_string(user.display_name, strict=strict)
    if not new_nick:
        new_nick = "Blessed by Sned"

    if new_nick == user.display_name:
        await ctx.mod_respond(
            embed=hikari.Embed(
                title="ℹ️ No action taken",
                description=f"The nickname of **{user.display_name}** is already deobfuscated or contains nothing to deobfuscate.",
                color=const.EMBED_BLUE,
            )
        )
        return

    await user.edit(nickname=new_nick, reason=f"{ctx.author} ({ctx.author.id}): Deobfuscated nickname")

    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Deobfuscated!",
            description=f"{user.mention}'s nickname is now: `{new_nick}`",
            color=const.EMBED_GREEN,
        )
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.VIEW_AUDIT_LOG, dm_enabled=False)
@lightbulb.command("journal", "Access and manage the moderation journal.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def journal(ctx: SnedSlashContext) -> None:
    pass


@journal.child
@lightbulb.option("user", "The user to retrieve the journal for.", type=hikari.User)
@lightbulb.command("get", "Retrieve the journal for the specified user.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def journal_get(ctx: SnedSlashContext, user: hikari.User) -> None:

    assert ctx.guild_id is not None
    notes = await ctx.app.mod.get_notes(user, ctx.guild_id)

    if notes:
        navigator = models.AuthorOnlyNavigator(ctx, pages=helpers.build_note_pages(notes))  # type: ignore
        ephemeral = bool((await ctx.app.mod.get_settings(ctx.guild_id)).flags & ModerationFlags.IS_EPHEMERAL)
        await navigator.send(ctx.interaction, ephemeral=ephemeral)

    else:
        await ctx.mod_respond(
            embed=hikari.Embed(
                title="📒 Journal entries for this user:",
                description=f"There are no journal entries for this user yet. Any moderation-actions will leave an entry here, or you can set one manually with `/journal add {ctx.options.user}`",
                color=const.EMBED_BLUE,
            )
        )


@journal.child
@lightbulb.option("note", "The journal note to add.")
@lightbulb.option("user", "The user to add a journal entry for.", type=hikari.User)
@lightbulb.command("add", "Add a new journal entry for the specified user.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def journal_add(ctx: SnedSlashContext, user: hikari.User, note: str) -> None:

    assert ctx.guild_id is not None

    await ctx.app.mod.add_note(user, ctx.guild_id, f"💬 **Note by {ctx.author}:** {note}")
    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Journal entry added!",
            description=f"Added a new journal entry to user **{user}**. You can view this user's journal via the command `/journal get {ctx.options.user}`.",
            color=const.EMBED_GREEN,
        )
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.VIEW_AUDIT_LOG, dm_enabled=False)
@lightbulb.add_checks(is_invoker_above_target)
@lightbulb.option("reason", "The reason for this warn", required=False)
@lightbulb.option("user", "The user to be warned.", type=hikari.Member)
@lightbulb.command(
    "warn", "Warn a user. This gets added to their journal and their warn counter is incremented.", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def warn_cmd(ctx: SnedSlashContext, user: hikari.Member, reason: t.Optional[str] = None) -> None:
    helpers.is_member(user)
    assert ctx.member is not None
    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    embed = await ctx.app.mod.warn(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.VIEW_AUDIT_LOG, dm_enabled=False)
@lightbulb.command("warns", "Manage warnings.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def warns(ctx: SnedSlashContext) -> None:
    pass


@warns.child
@lightbulb.option("user", "The user to show the warning count for.", type=hikari.Member)
@lightbulb.command("list", "List the current warning count for a user.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def warns_list(ctx: SnedSlashContext, user: hikari.Member) -> None:
    helpers.is_member(user)
    assert ctx.guild_id is not None

    db_user = await DatabaseUser.fetch(user.id, ctx.guild_id)
    warns = db_user.warns
    embed = hikari.Embed(
        title=f"{user}'s warnings",
        description=f"**Warnings:** `{warns}`",
        color=const.WARN_COLOR,
    )
    embed.set_thumbnail(user.display_avatar_url)
    await ctx.mod_respond(embed=embed)


@warns.child
@lightbulb.add_checks(is_invoker_above_target)
@lightbulb.option("reason", "The reason for clearing this user's warns.", required=False)
@lightbulb.option("user", "The user to clear warnings for.", type=hikari.Member)
@lightbulb.command("clear", "Clear warnings for the specified user.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def warns_clear(ctx: SnedSlashContext, user: hikari.Member, reason: t.Optional[str] = None) -> None:
    helpers.is_member(user)

    assert ctx.guild_id is not None and ctx.member is not None
    embed = await ctx.app.mod.clear_warns(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@warns.child
@lightbulb.add_checks(is_invoker_above_target)
@lightbulb.option("reason", "The reason for clearing this user's warns.", required=False)
@lightbulb.option("user", "The user to show the warning count for.", type=hikari.Member)
@lightbulb.command("remove", "Remove a single warning from the specified user.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def warns_remove(ctx: SnedSlashContext, user: hikari.Member, reason: t.Optional[str] = None) -> None:
    helpers.is_member(user)

    assert ctx.guild_id is not None and ctx.member is not None

    embed = await ctx.app.mod.remove_warn(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.MODERATE_MEMBERS, dm_enabled=False)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.MODERATE_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option("reason", "The reason for timing out this user.", required=False)
@lightbulb.option(
    "duration", "The duration to time the user out for. Example: '10 minutes', '2022-03-01', 'tomorrow 20:00'"
)
@lightbulb.option("user", "The user to time out.", type=hikari.Member)
@lightbulb.command("timeout", "Timeout a user, supports durations longer than 28 days.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def timeout_cmd(
    ctx: SnedSlashContext, user: hikari.Member, duration: str, reason: t.Optional[str] = None
) -> None:
    helpers.is_member(user)
    reason = helpers.format_reason(reason, max_length=1024)
    assert ctx.member is not None

    if user.communication_disabled_until() is not None:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ User already timed out",
                description="User is already timed out. Use `/timeouts remove` to remove it.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return
    try:
        communication_disabled_until: datetime.datetime = await ctx.app.scheduler.convert_time(
            duration, user=ctx.user, future_time=True
        )
    except ValueError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid data entered",
                description="Your entered timeformat is invalid.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    embed = await ctx.app.mod.timeout(user, ctx.member, communication_disabled_until, reason)

    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.MODERATE_MEMBERS, dm_enabled=False)
@lightbulb.command("timeouts", "Manage timeouts.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def timeouts(ctx: SnedSlashContext) -> None:
    pass


@timeouts.child
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.MODERATE_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option("reason", "The reason for timing out this user.", required=False)
@lightbulb.option("user", "The user to time out.", type=hikari.Member)
@lightbulb.command("remove", "Remove timeout from a user.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def timeouts_remove_cmd(ctx: SnedSlashContext, user: hikari.Member, reason: t.Optional[str] = None) -> None:
    helpers.is_member(user)
    reason = helpers.format_reason(reason, max_length=1024)

    assert ctx.member is not None

    if user.communication_disabled_until() is None:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ User not timed out",
                description="This user is not timed out.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    await ctx.app.mod.remove_timeout(user, ctx.member, reason)

    await ctx.mod_respond(
        embed=hikari.Embed(
            title="🔉 " + "Timeout removed",
            description=f"**{user}**'s timeout was removed.\n**Reason:** ```{reason}```",
            color=const.EMBED_GREEN,
        ),
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.BAN_MEMBERS, dm_enabled=False)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.BAN_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option(
    "days_to_delete",
    "The number of days of messages to delete. If not set, defaults to 0.",
    choices=["0", "1", "2", "3", "4", "5", "6", "7"],
    required=False,
    default=0,
)
@lightbulb.option(
    "duration",
    "If specified, how long the ban should last. Example: '10 minutes', '2022-03-01', 'tomorrow 20:00'",
    required=False,
)
@lightbulb.option("reason", "The reason why this ban was performed", required=False)
@lightbulb.option("user", "The user to be banned", type=hikari.User)
@lightbulb.command(
    "ban", "Bans a user from the server. Optionally specify a duration to make this a tempban.", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def ban_cmd(
    ctx: SnedSlashContext,
    user: hikari.User,
    reason: t.Optional[str] = None,
    duration: t.Optional[str] = None,
    days_to_delete: t.Optional[str] = None,
) -> None:

    assert ctx.member is not None

    if duration:
        try:
            banned_until = await ctx.app.scheduler.convert_time(duration, user=ctx.user, future_time=True)
        except ValueError:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Invalid data entered",
                    description="Your entered timeformat is invalid.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return
    else:
        banned_until = None

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    embed = await ctx.app.mod.ban(
        user,
        ctx.member,
        duration=banned_until,
        days_to_delete=int(days_to_delete) if days_to_delete else 0,
        reason=reason,
    )
    await ctx.mod_respond(
        embed=embed,
        components=(
            miru.View()
            .add_item(
                miru.Button(
                    label="Unban", custom_id=f"UNBAN:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SUCCESS
                )
            )
            .add_item(
                miru.Button(
                    label="View Journal",
                    custom_id=f"JOURNAL:{user.id}:{ctx.member.id}",
                    style=hikari.ButtonStyle.SECONDARY,
                )
            )
        ),
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.KICK_MEMBERS, dm_enabled=False)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.BAN_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option(
    "days_to_delete",
    "The number of days of messages to delete. If not set, defaults to 0.",
    choices=["0", "1", "2", "3", "4", "5", "6", "7"],
    required=False,
    default=0,
)
@lightbulb.option("reason", "The reason why this softban was performed", required=False)
@lightbulb.option("user", "The user to be softbanned", type=hikari.Member)
@lightbulb.command(
    "softban",
    "Softban a user from the server, removing their messages while immediately unbanning them.",
    pass_options=True,
)
@lightbulb.implements(lightbulb.SlashCommand)
async def softban_cmd(
    ctx: SnedSlashContext, user: hikari.Member, reason: t.Optional[str] = None, days_to_delete: t.Optional[str] = None
) -> None:
    helpers.is_member(user)
    assert ctx.member is not None

    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    embed = await ctx.app.mod.ban(
        user,
        ctx.member,
        soft=True,
        days_to_delete=int(days_to_delete) if days_to_delete else 0,
        reason=reason,
    )
    await ctx.mod_respond(embed=embed)


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.BAN_MEMBERS, dm_enabled=False)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.BAN_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option("reason", "The reason why this ban was performed", required=False)
@lightbulb.option("user", "The user to be banned", type=hikari.User)
@lightbulb.command("unban", "Unban a user who was previously banned.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def unban_cmd(ctx: SnedSlashContext, user: hikari.User, reason: t.Optional[str] = None) -> None:

    assert ctx.member is not None

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    embed = await ctx.app.mod.unban(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.KICK_MEMBERS, dm_enabled=False)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.KICK_MEMBERS),
    is_above_target,
    is_invoker_above_target,
)
@lightbulb.option("reason", "The reason why this kick was performed.", required=False)
@lightbulb.option("user", "The user to be banned", type=hikari.Member)
@lightbulb.command("kick", "Kick a user from this server.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def kick_cmd(ctx: SnedSlashContext, user: hikari.Member, reason: t.Optional[str] = None) -> None:

    helpers.is_member(user)
    assert ctx.member is not None

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    embed = await ctx.app.mod.kick(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.MANAGE_CHANNELS, dm_enabled=False)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.MANAGE_CHANNELS, hikari.Permissions.MANAGE_MESSAGES),
)
@lightbulb.option(
    "interval", "The slowmode interval in seconds, use 0 to disable it.", type=int, min_value=0, max_value=21600
)
@lightbulb.command("slowmode", "Set slowmode interval for this channel.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def slowmode_mcd(ctx: SnedSlashContext, interval: int) -> None:
    await ctx.app.rest.edit_channel(ctx.channel_id, rate_limit_per_user=interval)
    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Slowmode updated",
            description=f"{const.EMOJI_SLOWMODE} Slowmode is now set to 1 message per `{interval}` seconds.",
            color=const.EMBED_GREEN,
        )
    )


@mod.command
@lightbulb.app_command_permissions(hikari.Permissions.ADMINISTRATOR, dm_enabled=False)
@lightbulb.set_max_concurrency(1, lightbulb.GuildBucket)
@lightbulb.add_cooldown(60.0, 1, bucket=lightbulb.GuildBucket)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.BAN_MEMBERS),
)
@lightbulb.option(
    "show",
    "Only perform this as a dry-run and only show users that would have been banned. Defaults to False.",
    type=bool,
    default=False,
    required=False,
)
@lightbulb.option("reason", "Reason to ban all matched users with.", required=False)
@lightbulb.option("regex", "A regular expression to match usernames against. Uses Python regex spec.", required=False)
@lightbulb.option(
    "no-avatar", "Only match users without an avatar. Defaults to False.", type=bool, default=False, required=False
)
@lightbulb.option(
    "no-roles", "Only match users without a role. Defaults to False.", type=bool, default=False, required=False
)
@lightbulb.option(
    "created", "Only match users that signed up to Discord x minutes before.", type=int, min_value=1, required=False
)
@lightbulb.option(
    "joined", "Only match users that joined this server x minutes before.", type=int, min_value=1, required=False
)
@lightbulb.option("joined-before", "Only match users that joined before this user.", type=hikari.Member, required=False)
@lightbulb.option("joined-after", "Only match users that joined after this user.", type=hikari.Member, required=False)
@lightbulb.command("massban", "Ban a large number of users based on a set of criteria. Useful for handling raids")
@lightbulb.implements(lightbulb.SlashCommand)
async def massban(ctx: SnedSlashContext) -> None:

    if ctx.options["joined-before"]:
        helpers.is_member(ctx.options["joined-before"])
    if ctx.options["joined-after"]:
        helpers.is_member(ctx.options["joined-after"])

    predicates = [
        lambda member: not member.is_bot,
        lambda member: member.id != ctx.author.id,
        lambda member: member.discriminator != "0000",  # Deleted users
    ]

    guild = ctx.get_guild()
    assert guild is not None

    me = guild.get_member(ctx.app.user_id)
    assert me is not None

    def is_above_member(member: hikari.Member, me: hikari.Member = me) -> bool:
        # Check if the bot's role is above the member's or not to reduce invalid requests.
        return helpers.is_above(me, member)

    predicates.append(is_above_member)

    if ctx.options.regex:
        try:
            regex = re.compile(ctx.options.regex)
        except re.error as error:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Invalid regex passed",
                    description=f"Failed parsing regex: ```{str(error)}```",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            assert ctx.invoked is not None and ctx.invoked.cooldown_manager is not None
            await ctx.invoked.cooldown_manager.reset_cooldown(ctx)
            return
        else:
            predicates.append(lambda member, regex=regex: regex.match(member.username))

    await ctx.mod_respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    # Ensure the specified guild is explicitly chunked
    await ctx.app.request_guild_members(guild, include_presences=False)

    members = list(guild.get_members().values())

    if ctx.options["no-avatar"]:
        predicates.append(lambda member: member.avatar_url is None)
    if ctx.options["no-roles"]:
        predicates.append(lambda member: len(member.role_ids) <= 1)

    now = helpers.utcnow()

    if ctx.options.created:

        def created(member: hikari.User, offset=now - datetime.timedelta(minutes=ctx.options.created)) -> bool:
            return member.created_at > offset

        predicates.append(created)

    if ctx.options.joined:

        def joined(member: hikari.User, offset=now - datetime.timedelta(minutes=ctx.options.joined)) -> bool:
            if not isinstance(member, hikari.Member):
                return True
            else:
                return member.joined_at and member.joined_at > offset

        predicates.append(joined)

    if ctx.options["joined-after"]:

        def joined_after(member: hikari.Member, joined_after=ctx.options["joined-after"]) -> bool:
            return member.joined_at and joined_after.joined_at and member.joined_at > joined_after.joined_at

        predicates.append(joined_after)

    if ctx.options["joined-before"]:

        def joined_before(member: hikari.Member, joined_before=ctx.options["joined-before"]) -> bool:
            return member.joined_at and joined_before.joined_at and member.joined_at < joined_before.joined_at

        predicates.append(joined_before)

    to_ban = [member for member in members if all(predicate(member) for predicate in predicates)][:5000]

    if len(to_ban) == 0:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ No members match criteria",
                description=f"No members found that match all criteria.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    content = [f"Sned Massban Session: {guild.name}   |  Matched members against criteria: {len(to_ban)}\n{now}\n"]

    for member in to_ban:
        content.append(f"{member} ({member.id})  |  Joined: {member.joined_at}  |  Created: {member.created_at}")

    content = "\n".join(content)
    file = hikari.Bytes(content.encode("utf-8"), "members_to_ban.txt")

    if ctx.options.show == True:
        await ctx.mod_respond(attachment=file)
        return

    reason = ctx.options.reason if ctx.options.reason is not None else "No reason provided."
    helpers.format_reason(reason, ctx.member, max_length=512)

    embed = hikari.Embed(
        title="⚠️ Confirm Massban",
        description=f"You are about to ban **{len(to_ban)}** users. Are you sure you want to do this? Please review the attached list above for a full list of matched users. The user journals will not be updated.",
        color=const.WARN_COLOR,
    )
    confirm_embed = hikari.Embed(
        title="Starting Massban...",
        description="This could take some time...",
        color=const.WARN_COLOR,
    )
    cancel_embed = hikari.Embed(
        title="Massban interrupted",
        description="Massban session was terminated prematurely. No users were banned.",
        color=const.ERROR_COLOR,
    )

    is_ephemeral = bool((await ctx.app.mod.get_settings(guild.id)).flags & ModerationFlags.IS_EPHEMERAL)
    flags = hikari.MessageFlag.EPHEMERAL if is_ephemeral else hikari.MessageFlag.NONE
    confirmed = await ctx.confirm(
        embed=embed,
        flags=flags,
        cancel_payload={"embed": cancel_embed, "flags": flags, "components": []},
        confirm_payload={"embed": confirm_embed, "flags": flags, "components": []},
        attachment=file,
    )

    if not confirmed:
        return

    userlog = ctx.app.get_plugin("Logging")
    if userlog:
        await userlog.d.actions.freeze_logging(guild.id)

    count = 0

    for member in to_ban:
        try:
            await guild.ban(member, reason=reason)
        except (hikari.HTTPError, hikari.ForbiddenError):
            pass
        else:
            count += 1

    file = hikari.Bytes(content.encode("utf-8"), "members_banned.txt")

    assert ctx.guild_id is not None and ctx.member is not None
    await ctx.app.dispatch(MassBanEvent(ctx.app, ctx.guild_id, ctx.member, len(to_ban), count, file, reason))

    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Massban finished",
            description=f"Banned **{count}/{len(to_ban)}** users.",
            color=const.EMBED_GREEN,
        )
    )

    if userlog:
        await userlog.d.actions.unfreeze_logging(ctx.guild_id)


def load(bot: SnedBot) -> None:
    bot.add_plugin(mod)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(mod)


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
