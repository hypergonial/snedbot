import enum
import logging
import typing as t

import hikari
import lightbulb
import miru

import models
from etc import const
from models import SnedBot, SnedSlashContext
from models.plugin import SnedPlugin
from models.rolebutton import RoleButton, RoleButtonMode
from utils import helpers
from utils.ratelimiter import BucketType, RateLimiter

logger = logging.getLogger(__name__)

role_buttons = SnedPlugin("Rolebuttons")

BUTTON_STYLES = {
    "Blurple": hikari.ButtonStyle.PRIMARY,
    "Grey": hikari.ButtonStyle.SECONDARY,
    "Green": hikari.ButtonStyle.SUCCESS,
    "Red": hikari.ButtonStyle.DANGER,
}
BUTTON_MODES = {
    "Toggle": RoleButtonMode.TOGGLE,
    "Add": RoleButtonMode.ADD_ONLY,
    "Remove": RoleButtonMode.REMOVE_ONLY,
}

role_button_ratelimiter = RateLimiter(2, 1, BucketType.MEMBER, wait=False)


class RoleButtonConfirmType(enum.Enum):
    """Types of confirmation prompts for rolebuttons."""

    ADD = "add"
    REMOVE = "remove"


class RoleButtonConfirmModal(miru.Modal):
    """A modal to handle editing of confirmation prompts for rolebuttons."""

    def __init__(self, role_button: RoleButton, type: RoleButtonConfirmType) -> None:
        super().__init__(f"Add rolebutton confirmation for button #{role_button.id}", timeout=600)
        self.add_item(
            miru.TextInput(
                label="Title",
                placeholder="Enter prompt title, leave empty to reset...",
                min_length=1,
                max_length=100,
                value=role_button.add_title if type == RoleButtonConfirmType.ADD else role_button.remove_title,
            )
        )
        self.add_item(
            miru.TextInput(
                label="Description",
                placeholder="Enter prompt description, leave empty to reset...",
                min_length=1,
                max_length=3000,
                style=hikari.TextInputStyle.PARAGRAPH,
                value=role_button.add_description
                if type == RoleButtonConfirmType.ADD
                else role_button.remove_description,
            )
        )
        self.role_button = role_button
        self.type = type

    async def callback(self, context: miru.ModalContext) -> None:
        values = list(context.values.values())

        if self.type == RoleButtonConfirmType.ADD:
            self.role_button.add_title = values[0].strip()
            self.role_button.add_description = values[1].strip()
        elif self.type == RoleButtonConfirmType.REMOVE:
            self.role_button.remove_title = values[0].strip()
            self.role_button.remove_description = values[1].strip()

        await self.role_button.update(context.author)

        await context.respond(
            embed=hikari.Embed(
                title=f"✅ Rolebutton confirmation prompt updated!",
                description=f"Confirmation prompt updated for button **#{self.role_button.id}**.",
                color=0x77B255,
            )
        )


@role_buttons.listener(miru.ComponentInteractionCreateEvent, bind=True)
async def rolebutton_listener(plugin: SnedPlugin, event: miru.ComponentInteractionCreateEvent) -> None:
    """Statelessly listen for rolebutton interactions"""

    if not event.interaction.custom_id.startswith("RB:"):
        return

    entry_id = int(event.interaction.custom_id.split(":")[1])
    role_id = int(event.interaction.custom_id.split(":")[2])

    if not event.context.guild_id:
        return

    role = plugin.app.cache.get_role(role_id)

    if not role:
        await event.context.respond(
            embed=hikari.Embed(
                title="❌ Orphaned",
                description="The role this button was pointing to was deleted! Contact an administrator!",
                color=0xFF0000,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    assert event.context.app_permissions is not None

    if not helpers.includes_permissions(event.context.app_permissions, hikari.Permissions.MANAGE_ROLES):
        await event.context.respond(
            embed=hikari.Embed(
                title="❌ Missing Permissions",
                description="Bot does not have `Manage Roles` permissions! Contact an administrator!",
                color=0xFF0000,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await role_button_ratelimiter.acquire(event.context)
    if role_button_ratelimiter.is_rate_limited(event.context):
        await event.context.respond(
            embed=hikari.Embed(
                title="❌ Slow Down!",
                description="You are clicking too fast!",
                color=0xFF0000,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await event.context.defer(hikari.ResponseType.DEFERRED_MESSAGE_CREATE, flags=hikari.MessageFlag.EPHEMERAL)

    try:
        assert event.context.member is not None
        role_button = await RoleButton.fetch(entry_id)

        if not role_button:  # This should theoretically never happen, but I do not trust myself
            await event.context.respond(
                embed=hikari.Embed(
                    title="❌ Missing Data",
                    description="The rolebutton you clicked on is missing data, or was improperly deleted! Contact an administrator!",
                    color=0xFF0000,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if role.id in event.context.member.role_ids:

            if role_button.mode in [RoleButtonMode.TOGGLE, RoleButtonMode.REMOVE_ONLY]:
                await event.context.member.remove_role(role, reason=f"Removed by role-button (ID: {entry_id})")
                embed = hikari.Embed(
                    title=f"✅ {role_button.remove_title or 'Role removed'}",
                    description=f"{role_button.remove_description or f'Removed role: {role.mention}'}",
                    color=0x77B255,
                )
            else:
                embed = hikari.Embed(
                    title="❌ Role already added",
                    description=f"You already have the role {role.mention}!",
                    color=0xFF0000,
                ).set_footer("This button is set to only add roles, not remove them.")

        else:

            if role_button.mode in [RoleButtonMode.TOGGLE, RoleButtonMode.ADD_ONLY]:
                await event.context.member.add_role(role, reason=f"Granted by role-button (ID: {entry_id})")
                embed = hikari.Embed(
                    title=f"✅ {role_button.add_title or 'Role added'}",
                    description=f"{role_button.add_description or f'Added role: {role.mention}'}",
                    color=0x77B255,
                )
                if not role_button.add_description and role_button.mode == RoleButtonMode.TOGGLE:
                    embed.set_footer("To remove the role, click the button again!")
            else:
                embed = hikari.Embed(
                    title="❌ Role already removed",
                    description=f"You do not have the role {role.mention}!",
                    color=0xFF0000,
                ).set_footer("This button is set to only remove roles, not add them.")

        await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    except (hikari.ForbiddenError, hikari.HTTPError):
        await event.context.respond(
            embed=hikari.Embed(
                title="❌ Insufficient permissions",
                description="Failed changing role due to an issue with permissions and/or role hierarchy! Please contact an administrator!",
                color=0xFF0000,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )


@role_buttons.command
@lightbulb.app_command_permissions(hikari.Permissions.MANAGE_ROLES, dm_enabled=False)
@lightbulb.command("rolebutton", "Commands relating to rolebuttons.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def rolebutton(ctx: SnedSlashContext) -> None:
    pass


@rolebutton.child
@lightbulb.command("list", "List all registered rolebuttons on this server.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_list(ctx: SnedSlashContext) -> None:

    assert ctx.guild_id is not None

    buttons = await RoleButton.fetch_all(ctx.guild_id)

    if not buttons:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Error: No role-buttons",
                description="There are no role-buttons for this server.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
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

    if not button or button.guild_id != ctx.guild_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Not found",
                description="There is no rolebutton by that ID. Check your existing rolebuttons via `/rolebutton list`",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    try:
        await button.delete(ctx.member)
    except hikari.ForbiddenError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Insufficient permissions",
                description=f"The bot cannot see and/or read messages in the channel where the button is supposed to be located (<#{button.channel_id}>).",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.respond(
        embed=hikari.Embed(
            title="✅ Deleted!",
            description=f"Rolebutton **#{button.id}** was successfully deleted!",
            color=const.EMBED_GREEN,
        )
    )


@rolebutton.child
@lightbulb.option(
    "mode",
    "The mode of operation for this rolebutton.",
    choices=["Toggle - Add & remove roles (default)", "Add - Only add roles", "Remove - Only remove roles"],
    required=False,
)
@lightbulb.option(
    "style", "Change the style of the button.", choices=["Blurple", "Grey", "Red", "Green"], required=False
)
@lightbulb.option(
    "label", "Change the label that should appear on the button. Type 'removelabel' to remove it.", required=False
)
@lightbulb.option("emoji", "Change the emoji that should appear in the button.", type=hikari.Emoji, required=False)
@lightbulb.option("role", "Change the role handed out by this button.", type=hikari.Role, required=False)
@lightbulb.option(
    "button_id", "The ID of the rolebutton to edit. You can get this via /rolebutton list", type=int, min_value=0
)
@lightbulb.command(
    "edit",
    "Edit an existing rolebutton.",
    pass_options=True,
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_edit(ctx: SnedSlashContext, **kwargs) -> None:
    assert ctx.guild_id is not None and ctx.member is not None
    params = {opt: value for opt, value in kwargs.items() if value is not None}

    button = await RoleButton.fetch(params.pop("button_id"))

    if not button or button.guild_id != ctx.guild_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Not found",
                description="There is no rolebutton by that ID. Check your existing rolebuttons via `/rolebutton list`",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if label := params.get("label"):
        params["label"] = label if label.casefold() != "removelabel" else None

    if style := params.pop("style", None):
        params["style"] = BUTTON_STYLES[style]

    if mode := params.pop("mode", None):
        params["mode"] = BUTTON_MODES[mode.split(" -")[0]]

    if emoji := params.get("emoji"):
        params["emoji"] = hikari.Emoji.parse(emoji)

    if role := params.pop("role", None):
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

        top_role = ctx.member.get_top_role()
        guild = ctx.get_guild()
        if not guild or not top_role:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Caching error",
                    description="Failed to resolve `top_role` and `guild` from cache. Please join our `/support` server for assistance.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if role.position >= top_role.position and not guild.owner_id == ctx.member.id:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Role Hierarchy Error",
                    description="You cannot create rolebuttons for roles that are higher or equal to your highest role's position.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        params["role_id"] = role.id

    for param, value in params.items():
        setattr(button, param, value)

    try:
        await button.update(ctx.member)
    except hikari.ForbiddenError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Insufficient permissions",
                description=f"The bot cannot edit the provided message due to insufficient permissions.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    embed = hikari.Embed(
        title="✅ Done!",
        description=f"Rolebutton **#{button.id}** was updated!",
        color=const.EMBED_GREEN,
    )
    await ctx.respond(embed=embed)


@rolebutton.child
@lightbulb.option(
    "mode",
    "The mode of operation for this rolebutton.",
    choices=["Toggle - Add & remove roles (default)", "Add - Only add roles", "Remove - Only remove roles"],
    required=False,
)
@lightbulb.option("label", "The label that should appear on the button.", required=False)
@lightbulb.option("style", "The style of the button.", choices=["Blurple", "Grey", "Red", "Green"], required=False)
@lightbulb.option("emoji", "The emoji that should appear in the button.", type=str)
@lightbulb.option("role", "The role that should be handed out by the button.", type=hikari.Role)
@lightbulb.option(
    "message_link",
    "The link of a message that MUST be from the bot, the rolebutton will be attached here.",
)
@lightbulb.command(
    "add",
    "Add a new rolebutton.",
    pass_options=True,
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_add(
    ctx: SnedSlashContext,
    message_link: str,
    role: hikari.Role,
    emoji: str,
    style: t.Optional[str] = None,
    label: t.Optional[str] = None,
    mode: t.Optional[str] = None,
) -> None:

    assert ctx.guild_id is not None and ctx.member is not None

    style = style or "Grey"
    mode = mode or "Toggle - Add & remove roles"

    message = await helpers.parse_message_link(ctx, message_link)
    if not message:
        return

    if message.author.id != ctx.app.user_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Message not authored by bot",
                description="This message was not sent by the bot, and thus it cannot be edited to add the button.\n\n**Tip:** If you want to create a new message for the rolebutton with custom content, use the `/echo` or `/embed` command!",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

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

    top_role = ctx.member.get_top_role()
    guild = ctx.get_guild()

    if not guild or not top_role:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Caching error",
                description="Failed to resolve `top_role` and `guild` from cache. Please join our `/support` server for assistance.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if role.position >= top_role.position and not guild.owner_id == ctx.member.id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Role Hierarchy Error",
                description="You cannot create rolebuttons for roles that are higher or equal to your highest role's position.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    parsed_emoji = hikari.Emoji.parse(emoji)
    buttonstyle = BUTTON_STYLES[style.capitalize()]

    try:
        button = await RoleButton.create(
            ctx.guild_id, message, role, parsed_emoji, buttonstyle, BUTTON_MODES[mode.split(" -")[0]], label, ctx.member
        )
    except ValueError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Too many buttons",
                description="This message has too many buttons attached to it already, please choose a different message!",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return
    except hikari.ForbiddenError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Insufficient permissions",
                description=f"The bot cannot edit the provided message due to insufficient permissions.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.respond(
        embed=hikari.Embed(
            title="✅ Done!",
            description=f"A new rolebutton for role {ctx.options.role.mention} in channel <#{message.channel_id}> has been created!",
            color=const.EMBED_GREEN,
        ).set_footer(f"Button ID: {button.id}")
    )


@rolebutton.child
@lightbulb.option(
    "prompt_type",
    "'add' is displayed to the user when the role is added, 'remove' is when it is removed.",
    choices=["add", "remove"],
)
@lightbulb.option(
    "button_id",
    "The ID of the rolebutton to set a prompt for. You can get this via /rolebutton list",
    type=int,
    min_value=0,
)
@lightbulb.command(
    "setprompt", "Set a custom confirmation prompt to display when the button is clicked.", pass_options=True
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_setprompt(ctx: SnedSlashContext, button_id: int, prompt_type: str) -> None:

    button = await RoleButton.fetch(button_id)
    if not button or button.guild_id != ctx.guild_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Not found",
                description="There is no rolebutton by that ID. Check your existing rolebuttons via `/rolebutton list`",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    modal = RoleButtonConfirmModal(button, RoleButtonConfirmType(prompt_type))
    await modal.send(ctx.interaction)


def load(bot: SnedBot) -> None:
    bot.add_plugin(role_buttons)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(role_buttons)


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
