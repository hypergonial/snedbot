import datetime
import logging
import re
import typing as t

import arc
import hikari
import miru

import src.models as models
from src.etc import const
from src.models import errors
from src.models.checks import is_above_target, is_invoker_above_target
from src.models.client import SnedClient, SnedContext, SnedPlugin
from src.models.db_user import DatabaseUser
from src.models.events import MassBanEvent
from src.models.journal import JournalEntry, JournalEntryType
from src.models.mod_actions import ModerationFlags
from src.utils import helpers

logger = logging.getLogger(__name__)

plugin = SnedPlugin("Moderation")


@plugin.include
@arc.slash_command(
    "whois", "Show user information about the target user.", default_permissions=hikari.Permissions.MANAGE_GUILD
)
async def whois(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to show information about.")],
) -> None:
    embed = await helpers.get_userinfo(ctx, user)
    await ctx.respond(embed=embed)


@plugin.include
@arc.user_command("Show Userinfo")
async def whois_user_command(
    ctx: SnedContext,
    target: hikari.User,
) -> None:
    embed = await helpers.get_userinfo(ctx, target)
    await ctx.respond(embed=embed)


role = plugin.include_slash_group(
    "role", "Manage roles using commands.", default_permissions=hikari.Permissions.MANAGE_ROLES
)


@role.include
@arc.slash_subcommand("add", "Add a role to the target user.")
async def role_add(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to add the role to.")],
    role: arc.Option[hikari.Role, arc.RoleParams("The role to add.")],
) -> None:
    if not helpers.is_member(user):
        return
    assert ctx.guild_id and ctx.member

    me = ctx.client.cache.get_member(ctx.guild_id, ctx.client.user_id)
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

    await ctx.client.rest.add_role_to_member(
        ctx.guild_id, user, role, reason=f"{ctx.member} ({ctx.member.id}): Added role via Sned"
    )
    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Role added", description=f"Added role {role.mention} to `{user}`.", color=const.EMBED_GREEN
        )
    )


@role.include
@arc.slash_subcommand("remove", "Remove a role from the target user.")
async def role_del(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to remove the role from.")],
    role: arc.Option[hikari.Role, arc.RoleParams("The role to remove.")],
) -> None:
    if not helpers.is_member(user):
        return
    assert ctx.guild_id and ctx.member

    me = ctx.client.cache.get_member(ctx.guild_id, ctx.client.user_id)
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

    await ctx.client.rest.remove_role_from_member(
        ctx.guild_id, user, role, reason=f"{ctx.member} ({ctx.member.id}): Removed role via Sned"
    )
    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Role removed", description=f"Removed role {role.mention} from `{user}`.", color=const.EMBED_GREEN
        )
    )


@plugin.include
@arc.with_hook(arc.channel_limiter(20.0, 1))
@arc.with_hook(arc.bot_has_permissions(hikari.Permissions.MANAGE_MESSAGES | hikari.Permissions.READ_MESSAGE_HISTORY))
@arc.slash_command(
    "purge",
    "Purge multiple messages in this channel.",
    default_permissions=hikari.Permissions.MANAGE_MESSAGES,
)
async def purge(
    ctx: SnedContext,
    count: arc.Option[int, arc.IntParams("The amount of messages to delete.", min=1, max=100)],
    user: arc.Option[hikari.User | None, arc.UserParams("Only delete messages authored by this user.")] = None,
    regex: arc.Option[str | None, arc.StrParams("Only delete messages that match with the regular expression.")] = None,
    embeds: arc.Option[bool, arc.BoolParams("Only delete messages that contain embeds.")] = False,
    links: arc.Option[bool, arc.BoolParams("Only delete messages that contain links.")] = False,
    invites: arc.Option[bool, arc.BoolParams("Only delete messages that contain Discord invites.")] = False,
    attachments: arc.Option[bool, arc.BoolParams("Only delete messages that contain files & images.")] = False,
    onlytext: arc.Option[bool, arc.BoolParams("Only delete messages that exclusively contain text.")] = False,
    notext: arc.Option[bool, arc.BoolParams("Only delete messages that do not contain text.")] = False,
    endswith: arc.Option[str | None, arc.StrParams("Only delete messages that end with the specified text.")] = None,
    startswith: arc.Option[
        str | None, arc.StrParams("Only delete messages that start with the specified text.")
    ] = None,
) -> None:
    channel = ctx.get_channel() or await ctx.client.rest.fetch_channel(ctx.channel_id)
    assert isinstance(channel, hikari.TextableGuildChannel)

    predicates = [
        # Ignore deferred typing indicator so it doesn't get deleted lmfao
        lambda message: not (hikari.MessageFlag.LOADING & message.flags)
    ]

    if regex:
        try:
            pattern = re.compile(regex)
        except Exception as error:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Invalid regex passed",
                    description=f"Failed parsing regex: ```{error}```",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            ctx.command.reset_all_limiters(ctx)
        else:
            predicates.append(lambda message: bool(pattern.match(message.content)) if message.content else False)

    if startswith:
        predicates.append(lambda message: message.content.startswith(startswith) if message.content else False)

    if endswith:
        predicates.append(lambda message: message.content.endswith(endswith) if message.content else False)

    if notext:
        predicates.append(lambda message: not message.content)

    if onlytext:
        predicates.append(lambda message: message.content and not message.attachments and not message.embeds)

    if attachments:
        predicates.append(lambda message: bool(message.attachments))

    if invites:
        predicates.append(
            lambda message: helpers.is_invite(message.content, fullmatch=False) if message.content else False
        )

    if links:
        predicates.append(
            lambda message: helpers.is_url(message.content, fullmatch=False) if message.content else False
        )

    if embeds:
        predicates.append(lambda message: bool(message.embeds))

    if user:
        predicates.append(lambda message: message.author.id == user.id)

    await ctx.defer()

    messages = (
        await ctx.client.rest.fetch_messages(channel)
        .take_until(lambda m: (helpers.utcnow() - datetime.timedelta(days=14)) > m.created_at)
        .filter(*predicates)
        .limit(count)
    )

    if messages:
        try:
            await ctx.client.rest.delete_messages(channel, messages)
            embed = hikari.Embed(
                title="🗑️ Messages purged",
                description=f"**{len(messages)}** messages have been deleted.",
                color=const.EMBED_GREEN,
            )

        except hikari.BulkDeleteError as error:
            embed = hikari.Embed(
                title="🗑️ Messages purged",
                description=f"Only **{len(error.deleted_messages)}/{len(messages)}** messages have been deleted due to an error.",
                color=const.WARN_COLOR,
            )
            raise error
    else:
        embed = hikari.Embed(
            title="🗑️ Not found",
            description="No messages matched the specified criteria from the past two weeks!",
            color=const.ERROR_COLOR,
        )

    await ctx.mod_respond(embed=embed)


@plugin.include
@arc.with_hook(is_invoker_above_target)
@arc.with_hook(is_above_target)
@arc.with_hook(arc.bot_has_permissions(hikari.Permissions.MANAGE_NICKNAMES))
@arc.slash_command(
    "deobfuscate", "Deobfuscate a user's nickname.", default_permissions=hikari.Permissions.MANAGE_NICKNAMES
)
async def deobfuscate(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user who's nickname should be deobfuscated.")],
    strict: arc.Option[
        bool, arc.BoolParams("If enabled, uses stricter filtering and may filter out certain valid letters.")
    ] = True,
) -> None:
    if not helpers.is_member(user):
        return

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


journal = plugin.include_slash_group(
    "journal", "Access and manage the moderation journal.", default_permissions=hikari.Permissions.VIEW_AUDIT_LOG
)


@journal.include
@arc.slash_subcommand("get", "Retrieve the journal for the specified user.")
async def journal_get(
    ctx: SnedContext, user: arc.Option[hikari.User, arc.UserParams("The user to retrieve the journal for.")]
) -> None:
    assert ctx.guild_id is not None
    journal = await JournalEntry.fetch_journal(user, ctx.guild_id)

    if journal:
        navigator = models.AuthorOnlyNavigator(ctx, pages=helpers.build_journal_pages(journal))  # type: ignore
        ephemeral = bool((await ctx.client.mod.get_settings(ctx.guild_id)).flags & ModerationFlags.IS_EPHEMERAL)
        await navigator.send(ctx.interaction, ephemeral=ephemeral)

    else:
        await ctx.mod_respond(
            embed=hikari.Embed(
                title="📒 Journal entries for this user:",
                description=f"There are no journal entries for this user yet. Any moderation-actions will leave an entry here, or you can set one manually with `/journal add {ctx.options.user}`",
                color=const.EMBED_BLUE,
            )
        )


@journal.include
@arc.slash_subcommand("add", "Add a new journal entry for the specified user.")
async def journal_add(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to add a journal entry for.")],
    note: arc.Option[str, arc.StrParams("The journal note to add.")],
) -> None:
    assert ctx.guild_id is not None
    await JournalEntry(
        user_id=user.id,
        guild_id=ctx.guild_id,
        entry_type=JournalEntryType.NOTE,
        content=note,
        author_id=ctx.author.id,
        created_at=helpers.utcnow(),
    ).update()

    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Journal entry added!",
            description=f"Added a new journal entry to user **{user}**. You can view this user's journal via the command `/journal get {ctx.options.user}`.",
            color=const.EMBED_GREEN,
        )
    )


@plugin.include
@arc.with_hook(is_invoker_above_target)
@arc.slash_command(
    "warn",
    "Warn a user. This gets added to their journal and their warn counter is incremented.",
    default_permissions=hikari.Permissions.VIEW_AUDIT_LOG,
)
async def warn_cmd(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to be warned.")],
    reason: arc.Option[str | None, arc.StrParams("The reason for this warn")] = None,
) -> None:
    if not helpers.is_member(user):
        return
    assert ctx.member is not None
    embed = await ctx.client.mod.warn(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


warns = plugin.include_slash_group("warns", "Manage warnings.", default_permissions=hikari.Permissions.VIEW_AUDIT_LOG)


@warns.include
@arc.slash_subcommand("list", "List the current warning count for a user.")
async def warns_list(
    ctx: SnedContext, user: arc.Option[hikari.User, arc.UserParams("The user to show the warning count for.")]
) -> None:
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


@warns.include
@arc.with_hook(is_invoker_above_target)
@arc.slash_subcommand("clear", "Clear warnings for the specified user.")
async def warns_clear(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to clear warnings for.")],
    reason: arc.Option[str | None, arc.StrParams("The reason for clearing this user's warns.")] = None,
) -> None:
    if not helpers.is_member(user):
        return

    assert ctx.guild_id is not None and ctx.member is not None
    embed = await ctx.client.mod.clear_warns(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@warns.include
@arc.with_hook(is_invoker_above_target)
@arc.slash_subcommand("remove", "Remove a single warning from the specified user.")
async def warns_remove(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to remove a warning from.")],
    reason: arc.Option[str | None, arc.StrParams("The reason for removing this user's warn.")] = None,
) -> None:
    if not helpers.is_member(user):
        return

    assert ctx.guild_id is not None and ctx.member is not None

    embed = await ctx.client.mod.remove_warn(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@plugin.include
@arc.with_hook(arc.bot_has_permissions(hikari.Permissions.MODERATE_MEMBERS))
@arc.with_hook(is_above_target)
@arc.with_hook(is_invoker_above_target)
@arc.slash_command(
    "timeout",
    "Timeout a user, supports durations longer than 28 days.",
    default_permissions=hikari.Permissions.MODERATE_MEMBERS,
)
async def timeout_cmd(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to time out.")],
    duration: arc.Option[
        str,
        arc.StrParams("The duration to time the user out for. Example: '10 minutes', '2022-03-01', 'tomorrow 20:00'"),
    ],
    reason: arc.Option[str | None, arc.StrParams("The reason for timing out this user.")] = None,
) -> None:
    if not helpers.is_member(user):
        return
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
        communication_disabled_until: datetime.datetime = await ctx.client.scheduler.convert_time(
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

    embed = await ctx.client.mod.timeout(user, ctx.member, communication_disabled_until, reason)

    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


timeouts = plugin.include_slash_group(
    "timeouts", "Manage timeouts.", default_permissions=hikari.Permissions.MODERATE_MEMBERS
)


@timeouts.include
@arc.with_hook(arc.bot_has_permissions(hikari.Permissions.MODERATE_MEMBERS))
@arc.with_hook(is_above_target)
@arc.with_hook(is_invoker_above_target)
@arc.slash_subcommand("remove", "Remove timeout from a user.")
async def timeouts_remove_cmd(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to time out.")],
    reason: arc.Option[str | None, arc.StrParams("The reason for timing out this user.")] = None,
) -> None:
    if not helpers.is_member(user):
        return
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

    await ctx.client.mod.remove_timeout(user, ctx.member, reason)

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


@plugin.include
@arc.with_hook(arc.bot_has_permissions(hikari.Permissions.BAN_MEMBERS))
@arc.with_hook(is_above_target)
@arc.with_hook(is_invoker_above_target)
@arc.slash_command(
    "ban",
    "Bans a user from the server. Optionally specify a duration to make this a tempban.",
    default_permissions=hikari.Permissions.BAN_MEMBERS,
)
async def ban_cmd(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to ban")],
    reason: arc.Option[str | None, arc.StrParams("The reason why this ban was performed")] = None,
    duration: arc.Option[
        str | None,
        arc.StrParams(
            "If specified, how long the ban should last. Example: '10 minutes', '2022-03-01', 'tomorrow 20:00'"
        ),
    ] = None,
    days_to_delete: arc.Option[
        int | None,
        arc.IntParams(
            "The number of days of messages to delete. If not set, defaults to 0.",
            choices=[1, 2, 3, 4, 5, 6, 7],
        ),
    ] = None,
) -> None:
    assert ctx.member is not None

    if duration:
        try:
            banned_until = await ctx.client.scheduler.convert_time(duration, user=ctx.user, future_time=True)
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

    embed = await ctx.client.mod.ban(
        user,
        ctx.member,
        duration=banned_until,
        days_to_delete=days_to_delete or 0,
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


@plugin.include
@arc.with_hook(arc.bot_has_permissions(hikari.Permissions.BAN_MEMBERS))
@arc.with_hook(is_above_target)
@arc.with_hook(is_invoker_above_target)
@arc.slash_command(
    "softban",
    "Softban a user from the server, removing their messages while immediately unbanning them.",
    default_permissions=hikari.Permissions.KICK_MEMBERS,
)
async def softban_cmd(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to softban")],
    days_to_delete: arc.Option[
        int,
        arc.IntParams(
            "The number of days of messages to delete.",
            choices=[1, 2, 3, 4, 5, 6, 7],
        ),
    ],
    reason: arc.Option[str | None, arc.StrParams("The reason why this softban was performed")] = None,
) -> None:
    helpers.is_member(user)
    assert ctx.member is not None

    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    embed = await ctx.client.mod.ban(
        user,
        ctx.member,
        soft=True,
        days_to_delete=days_to_delete,
        reason=reason,
    )
    await ctx.mod_respond(
        embed=embed,
        components=(
            miru.View().add_item(
                miru.Button(
                    label="View Journal",
                    custom_id=f"JOURNAL:{user.id}:{ctx.member.id}",
                    style=hikari.ButtonStyle.SECONDARY,
                )
            )
        ),
    )


@plugin.include
@arc.with_hook(arc.bot_has_permissions(hikari.Permissions.BAN_MEMBERS))
@arc.with_hook(is_above_target)
@arc.with_hook(is_invoker_above_target)
@arc.slash_command(
    "unban", "Unban a user who was previously banned.", default_permissions=hikari.Permissions.BAN_MEMBERS
)
async def unban_cmd(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to unban")],
    reason: arc.Option[str | None, arc.StrParams("The reason for performing this unban")] = None,
) -> None:
    assert ctx.member is not None

    embed = await ctx.client.mod.unban(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@plugin.include
@arc.with_hook(arc.bot_has_permissions(hikari.Permissions.KICK_MEMBERS))
@arc.with_hook(is_above_target)
@arc.with_hook(is_invoker_above_target)
@arc.slash_command("kick", "Kick a user from this server.", default_permissions=hikari.Permissions.KICK_MEMBERS)
async def kick_cmd(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to kick")],
    reason: arc.Option[str | None, arc.StrParams("The reason for performing this kick")] = None,
) -> None:
    if not helpers.is_member(user):
        return

    assert ctx.member is not None

    embed = await ctx.client.mod.kick(user, ctx.member, reason=reason)
    await ctx.mod_respond(
        embed=embed,
        components=miru.View().add_item(
            miru.Button(
                label="View Journal", custom_id=f"JOURNAL:{user.id}:{ctx.member.id}", style=hikari.ButtonStyle.SECONDARY
            )
        ),
    )


@plugin.include
@arc.with_hook(
    arc.bot_has_permissions(hikari.Permissions.MANAGE_CHANNELS | hikari.Permissions.MANAGE_MESSAGES),
)
@arc.slash_command(
    "slowmode", "Set slowmode interval for this channel.", default_permissions=hikari.Permissions.MANAGE_CHANNELS
)
async def slowmode_mcd(
    ctx: SnedContext,
    interval: arc.Option[
        int, arc.IntParams("The slowmode interval in seconds, use 0 to disable it.", min=0, max=21600)
    ],
) -> None:
    await ctx.client.rest.edit_channel(ctx.channel_id, rate_limit_per_user=interval)
    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Slowmode updated",
            description=f"{const.EMOJI_SLOWMODE} Slowmode is now set to 1 message per `{interval}` seconds.",
            color=const.EMBED_GREEN,
        )
    )


@plugin.include
@arc.with_concurrency_limit(arc.guild_concurrency(1))
@arc.with_hook(arc.guild_limiter(180.0, 1))
@arc.with_hook(
    arc.bot_has_permissions(hikari.Permissions.BAN_MEMBERS),
)
@arc.slash_command(
    "massban",
    "Ban a large number of users based on a set of criteria. Useful for handling raids",
    default_permissions=hikari.Permissions.ADMINISTRATOR,
)
async def massban(
    ctx: SnedContext,
    joined_after: arc.Option[
        hikari.User | None, arc.UserParams("Only match users that joined after this user.", name="joined-after")
    ] = None,
    joined_before: arc.Option[
        hikari.User | None, arc.UserParams("Only match users that joined before this user.", name="joined-before")
    ] = None,
    joined: arc.Option[
        int | None, arc.IntParams("Only match users that joined this server x minutes before.", min=1)
    ] = None,
    created: arc.Option[
        int | None, arc.IntParams("Only match users that signed up to Discord x minutes before.", min=1)
    ] = None,
    no_roles: arc.Option[
        bool | None, arc.BoolParams("Only match users without a role. Defaults to False.", name="no-roles")
    ] = None,
    no_avatar: arc.Option[
        bool | None, arc.BoolParams("Only match users without an avatar. Defaults to False.", name="no-avatar")
    ] = None,
    regex: arc.Option[
        str | None, arc.StrParams("A regular expression to match usernames against. Uses Python regex spec.")
    ] = None,
    reason: arc.Option[str | None, arc.StrParams("Reason to ban all matched users with.")] = None,
    show: arc.Option[
        bool | None,
        arc.BoolParams(
            "Only perform this as a dry-run and only show users that would have been banned. Defaults to False."
        ),
    ] = None,
) -> None:
    if joined_before:
        helpers.is_member(joined_before)
    if joined_after:
        helpers.is_member(joined_after)

    guild = ctx.get_guild()
    assert guild is not None

    me = guild.get_member(ctx.client.user_id)
    assert me is not None

    predicates: list[t.Callable[[hikari.Member], bool]] = [
        lambda m: not m.is_bot,
        lambda m: m.id != ctx.author.id,
        lambda m: helpers.is_above(me, m),  # Only ban users below bot
    ]

    if regex:
        try:
            compiled_regex = re.compile(regex)
        except re.error as error:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Invalid regex passed",
                    description=f"Failed parsing regex: ```{error}```",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return ctx.command.reset_all_limiters(ctx)
        else:
            predicates.append(lambda member: bool(compiled_regex.match(member.username)))

    if no_avatar:
        predicates.append(lambda member: member.avatar_url is None)
    if no_roles:
        predicates.append(lambda member: len(member.role_ids) <= 1)

    now = helpers.utcnow()

    if created:  # why ruff add blank line below :(

        def created_(member: hikari.User, offset=now - datetime.timedelta(minutes=created)) -> bool:
            return member.created_at > offset

        predicates.append(created_)

    if joined:

        def joined_(member: hikari.User, offset=now - datetime.timedelta(minutes=joined)) -> bool:
            if not isinstance(member, hikari.Member):
                return True
            else:
                return member.joined_at and member.joined_at > offset

        predicates.append(joined_)

    # TODO: these functions are gonna have to be renamed as they overwrite the function params
    if joined_after and helpers.is_member(joined_after):

        def joined_after_(member: hikari.Member, joined_after=joined_after) -> bool:
            return member.joined_at and joined_after.joined_at and member.joined_at > joined_after.joined_at

        predicates.append(joined_after_)

    if joined_before and helpers.is_member(joined_before):

        def joined_before_(member: hikari.Member, joined_before=joined_before) -> bool:
            return member.joined_at and joined_before.joined_at and member.joined_at < joined_before.joined_at

        predicates.append(joined_before_)

    if len(predicates) == 3:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ No criteria specified",
                description="You must specify at least one criteria to match against.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return ctx.command.reset_all_limiters(ctx)

    # Ensure the specified guild is explicitly chunked
    await ctx.client.app.request_guild_members(guild, include_presences=False)

    members = list(guild.get_members().values())

    to_ban = [member for member in members if all(predicate(member) for predicate in predicates)][:5000]

    if len(to_ban) == 0:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ No members match criteria",
                description="No members found that match all criteria.",
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

    if show is True:
        await ctx.mod_respond(attachment=file)
        return

    reason = reason or "No reason provided."
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

    is_ephemeral = bool((await ctx.client.mod.get_settings(guild.id)).flags & ModerationFlags.IS_EPHEMERAL)
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

    # FIXME: This abomination needs to be utterly destroyed
    userlog = ctx.client.get_plugin("Logging")
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
    await ctx.client.app.dispatch(
        MassBanEvent(ctx.client.app, ctx.guild_id, ctx.member, len(to_ban), count, file, reason)
    )

    await ctx.mod_respond(
        embed=hikari.Embed(
            title="✅ Massban finished",
            description=f"Banned **{count}/{len(to_ban)}** users.",
            color=const.EMBED_GREEN,
        )
    )

    if userlog:
        await userlog.d.actions.unfreeze_logging(ctx.guild_id)


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
