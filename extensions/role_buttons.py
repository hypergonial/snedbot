import logging
import typing as t

import asyncpg
import hikari
import lightbulb
import miru

import models
from etc import constants as const
from models import SnedBot
from models import SnedSlashContext
from models.checks import has_permissions
from models.rolebutton import RoleButton
from utils import helpers
from utils.ratelimiter import BucketType
from utils.ratelimiter import RateLimiter

logger = logging.getLogger(__name__)

role_buttons = lightbulb.Plugin("Role-Buttons")

button_styles = {
    "Blurple": hikari.ButtonStyle.PRIMARY,
    "Grey": hikari.ButtonStyle.SECONDARY,
    "Green": hikari.ButtonStyle.SUCCESS,
    "Red": hikari.ButtonStyle.DANGER,
}
role_button_ratelimiter = RateLimiter(2, 1, BucketType.MEMBER, wait=False)


@role_buttons.listener(miru.ComponentInteractionCreateEvent, bind=True)
async def rolebutton_listener(plugin: lightbulb.Plugin, event: miru.ComponentInteractionCreateEvent) -> None:
    """Statelessly listen for rolebutton interactions"""

    if not event.interaction.custom_id.startswith("RB:"):
        return

    assert isinstance(plugin.app, SnedBot)

    entry_id = event.interaction.custom_id.split(":")[1]
    role_id = int(event.interaction.custom_id.split(":")[2])

    if not event.context.guild_id:
        return

    role = plugin.app.cache.get_role(role_id)

    if not role:
        embed = hikari.Embed(
            title="❌ Orphaned",
            description="The role this button was pointing to was deleted! Please notify an administrator!",
            color=0xFF0000,
        )
        await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    me = plugin.app.cache.get_member(event.context.guild_id, plugin.app.user_id)
    assert me is not None

    if not helpers.includes_permissions(lightbulb.utils.permissions_for(me), hikari.Permissions.MANAGE_ROLES):
        embed = hikari.Embed(
            title="❌ Missing Permissions",
            description="Bot does not have `Manage Roles` permissions! Contact an administrator!",
            color=0xFF0000,
        )
        await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    await role_button_ratelimiter.acquire(event.context)
    if role_button_ratelimiter.is_rate_limited(event.context):
        embed = hikari.Embed(
            title="❌ Slow Down!",
            description="You are clicking too fast!",
            color=0xFF0000,
        )
        await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    await event.context.defer(hikari.ResponseType.DEFERRED_MESSAGE_CREATE, flags=hikari.MessageFlag.EPHEMERAL)

    try:
        assert event.context.member is not None

        if role.id in event.context.member.role_ids:
            await event.context.member.remove_role(role, reason=f"Removed by role-button (ID: {entry_id})")
            embed = hikari.Embed(
                title="✅ Role removed",
                description=f"Removed role: {role.mention}",
                color=0x77B255,
            )
            await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        else:
            await event.context.member.add_role(role, reason=f"Granted by role-button (ID: {entry_id})")
            embed = hikari.Embed(
                title="✅ Role added",
                description=f"Added role: {role.mention}",
                color=0x77B255,
            )
            embed.set_footer(text="If you would like it removed, click the button again!")
            await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    except (hikari.ForbiddenError, hikari.HTTPError):
        embed = hikari.Embed(
            title="❌ Insufficient permissions",
            description="Failed adding role due to an issue with permissions and/or role hierarchy! Please contact an administrator!",
            color=0xFF0000,
        )
        await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@role_buttons.command
@lightbulb.command("rolebutton", "Commands relating to rolebuttons.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def rolebutton(ctx: SnedSlashContext) -> None:
    pass


@rolebutton.child
@lightbulb.add_checks(has_permissions(hikari.Permissions.MANAGE_ROLES))
@lightbulb.command("list", "List all registered rolebuttons on this server.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_list(ctx: SnedSlashContext) -> None:

    assert ctx.guild_id is not None

    buttons = await RoleButton.fetch_all(ctx.guild_id)

    if not buttons:
        embed = hikari.Embed(
            title="❌ Error: No role-buttons",
            description="There are no role-buttons for this server.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    paginator = lightbulb.utils.StringPaginator(max_chars=500)
    for button in buttons:
        role = ctx.app.cache.get_role(button.role_id)
        channel = ctx.app.cache.get_guild_channel(button.channel_id)

        if role and channel:
            paginator.add_line(f"**#{button.id}** - {channel.mention} - {role.mention}")

        else:
            paginator.add_line(f"**#{button.id}** - C: `{button.channel_id}` - R: `{button.role_id}`")

    embeds = [
        hikari.Embed(
            title="Rolebuttons on this server:",
            description=page,
            color=const.EMBED_BLUE,
        )
        for page in paginator.build_pages()
    ]

    navigator = models.AuthorOnlyNavigator(ctx, pages=embeds)  # type: ignore
    await navigator.send(ctx.interaction)


@rolebutton.child
@lightbulb.add_checks(has_permissions(hikari.Permissions.MANAGE_ROLES))
@lightbulb.option(
    "button_id",
    "The ID of the rolebutton to delete. You can get this via /rolebutton list",
    type=int,
    min_value=0,
)
@lightbulb.command("delete", "Delete a rolebutton.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_del(ctx: SnedSlashContext, button_id: int) -> None:
    assert ctx.guild_id is not None

    button = await RoleButton.fetch(button_id)

    if not button:
        embed = hikari.Embed(
            title="❌ Not found",
            description="There is no rolebutton by that ID. Check your existing rolebuttons via `/rolebutton list`",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    try:
        await button.delete(ctx.app.rest)
    except hikari.ForbiddenError:
        embed = hikari.Embed(
            title="❌ Insufficient permissions",
            description=f"The bot cannot see and/or read messages in the channel where the button is supposed to be located (<#{button.channel_id}>).",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    embed = hikari.Embed(
        title="✅ Deleted!",
        description=f"Rolebutton **#{button.id}** was successfully deleted!",
        color=const.EMBED_GREEN,
    )
    await ctx.respond(embed=embed)


@rolebutton.child
@lightbulb.add_checks(has_permissions(hikari.Permissions.MANAGE_ROLES))
@lightbulb.option("buttonstyle", "The style of the button.", choices=["Blurple", "Grey", "Red", "Green"])
@lightbulb.option("label", "The label that should appear on the button.", required=False)
@lightbulb.option("emoji", "The emoji that should appear in the button.", type=hikari.Emoji)
@lightbulb.option("role", "The role that should be handed out by the button.", type=hikari.Role)
@lightbulb.option(
    "message_link",
    "The link of a message that MUST be from the bot, the rolebutton will be attached here.",
)
@lightbulb.command(
    "add",
    "Add a new rolebutton.",
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_add(ctx: SnedSlashContext) -> None:

    assert ctx.guild_id is not None

    buttonstyle = ctx.options.buttonstyle or "Grey"

    message = await helpers.parse_message_link(ctx, ctx.options.message_link)
    if not message:
        return

    if message.author.id != ctx.app.user_id:
        embed = hikari.Embed(
            title="❌ Message not authored by bot",
            description="This message was not sent by the bot, and thus it cannot be edited to add the button.\n\n**Tip:** If you want to create a new message for the rolebutton with custom content, use the `/echo` or `/embed` command!",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    record = await ctx.app.db.fetchrow("""SELECT entry_id FROM button_roles ORDER BY entry_id DESC""")
    entry_id = record.get("entry_id") + 1 if record else 1
    emoji = hikari.Emoji.parse(ctx.options.emoji)
    style = button_styles[buttonstyle.capitalize()]

    try:
        button = await RoleButton.create(ctx.guild_id, message, ctx.options.role, emoji, style, ctx.options.label)
    except ValueError:
        embed = hikari.Embed(
            title="❌ Too many buttons",
            description="This message has too many buttons attached to it already, please choose a different message!",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return
    except hikari.ForbiddenError:
        embed = hikari.Embed(
            title="❌ Insufficient permissions",
            description=f"The bot cannot edit the provided message due to insufficient permissions.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    embed = hikari.Embed(
        title="✅ Done!",
        description=f"A new rolebutton for role {ctx.options.role.mention} in channel <#{message.channel_id}> has been created!",
        color=const.EMBED_GREEN,
    )
    await ctx.respond(embed=embed)

    embed = hikari.Embed(
        title="❇️ Role-Button was added",
        description=f"A role-button for role {ctx.options.role.mention} has been created by {ctx.author.mention} in channel <#{message.channel_id}>.\n\n__Note:__ Anyone who can see this channel can now obtain this role!",
        color=const.EMBED_GREEN,
    )

    userlog = ctx.app.get_plugin("Logging")
    assert userlog is not None
    await userlog.d.actions.log("roles", embed, ctx.guild_id)


def load(bot: SnedBot) -> None:
    bot.add_plugin(role_buttons)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(role_buttons)
