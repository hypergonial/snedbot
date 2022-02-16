import asyncio
import copy
import json
import logging
import typing as t

import hikari
import lightbulb
import miru
import models
from etc.settings_static import *
from models.bot import SnedBot
from models.context import SnedContext, SnedSlashContext
from utils import helpers

logger = logging.getLogger(__name__)

settings = lightbulb.Plugin("Settings")


def get_key(dictionary: dict, value: t.Any) -> t.Any:
    """
    Get key from value in dict, too lazy to copy this garbage
    """
    return list(dictionary.keys())[list(dictionary.values()).index(value)]


class SettingsView(models.AuthorOnlyView):
    def __init__(self, lctx: lightbulb.Context, *, timeout: t.Optional[float] = 120, autodefer: bool = False) -> None:
        super().__init__(lctx, timeout=timeout, autodefer=autodefer)
        self.last_ctx: t.Optional[t.Union[miru.Context, SnedContext]] = lctx


class SettingsContext(SnedSlashContext):
    """Abuse subclassing to get custom data into other functions c:"""

    def __init__(
        self, app: lightbulb.BotApp, event: hikari.InteractionCreateEvent, command: lightbulb.SlashCommand
    ) -> None:
        super().__init__(app, event, command)
        self.parent: t.Optional[str] = None
        self.last_inter: t.Optional[
            t.Union[miru.ComponentInteraction, miru.ModalInteraction]
        ] = None  # Last inter received


# Settings Menu Views


class BooleanButton(miru.Button):
    """A boolean toggle button."""

    def __init__(self, *, state: bool, label: str = None, disabled: bool = False, row: t.Optional[int] = None) -> None:
        style = hikari.ButtonStyle.SUCCESS if state else hikari.ButtonStyle.DANGER
        emoji = "✔️" if state else "✖️"

        self.state = state

        super().__init__(style=style, label=label, emoji=emoji, disabled=disabled, row=row)

    async def callback(self, context: miru.ViewContext) -> None:
        self.state = not self.state

        self.style = hikari.ButtonStyle.SUCCESS if self.state else hikari.ButtonStyle.DANGER
        self.emoji = "✔️" if self.state else "✖️"
        self.view.value = (self.label, self.state)
        self.view.lctx.last_inter = context.interaction

        self.view.stop()


class OptionButton(miru.Button):
    """Button that sets view value to label, stops view."""

    async def callback(self, context: miru.ViewContext) -> None:
        if not isinstance(self.view, MenuBaseView):
            return

        self.view.value = self.label
        self.view.lctx.last_inter = context.interaction
        self.view.stop()


class OptionsSelect(miru.Select):
    """Select that sets view value to first selected option's value."""

    async def callback(self, context: miru.ViewContext) -> None:
        if not isinstance(self.view, MenuBaseView):
            return

        self.view.value = self.values[0]
        self.view.lctx.last_inter = context.interaction
        self.view.stop()


class BackButton(OptionButton):
    """Go back to page that ctx.parent is set to."""

    def __init__(self) -> None:
        super().__init__(style=hikari.ButtonStyle.PRIMARY, label="Back", emoji="⬅️")


class QuitButton(OptionButton):
    """Quit settings, delete message."""

    def __init__(self) -> None:
        super().__init__(style=hikari.ButtonStyle.DANGER, label="Quit", emoji="⬅️")


class MenuBaseView(models.AuthorOnlyView):
    """Base menu class all other views depend on."""

    def __init__(
        self,
        lctx: lightbulb.Context,
        is_nested: bool = False,
        *,
        timeout: t.Optional[float] = 120,
        autodefer: bool = True,
    ) -> None:
        super().__init__(lctx, timeout=timeout, autodefer=autodefer)
        self.is_nested: bool = is_nested
        self.value: str = None

    async def on_timeout(self) -> None:
        self.value = "Timeout"


class ButtonMenuView(MenuBaseView):
    """Button-based menu system"""

    def __init__(
        self,
        lctx: lightbulb.Context,
        buttons: t.Optional[t.List[OptionButton]] = None,
        is_nested: bool = False,
        *,
        timeout: t.Optional[float] = 120,
        autodefer: bool = True,
    ) -> None:
        super().__init__(lctx, timeout=timeout, autodefer=autodefer)

        if is_nested:
            self.add_item(BackButton())
        else:
            self.add_item(QuitButton())

        if buttons:
            for button in buttons:
                self.add_item(button)


class SelectMenuView(MenuBaseView):
    """Select menu based menu system"""

    def __init__(
        self,
        lctx: lightbulb.Context,
        options: t.List[miru.SelectOption],
        placeholder: str,
        is_nested: bool = False,
        *,
        timeout: t.Optional[float] = 120,
        autodefer: bool = True,
    ) -> None:
        super().__init__(lctx, timeout=timeout, autodefer=autodefer)
        self.add_item(OptionsSelect(options=options, placeholder=placeholder))

        if is_nested:
            self.add_item(BackButton())
        else:
            self.add_item(QuitButton())


# Menu functions and handling


async def error_view_handler(
    ctx: SettingsContext, message: hikari.Message, embed: hikari.Embed, return_to: str
) -> None:
    """Add a standard 'Back' button below the error message to return to previous step."""
    ctx.parent = return_to
    view = ButtonMenuView(ctx, is_nested=True)
    await helpers.maybe_edit(message, embed=embed, components=view.build())
    view.start(message)
    await view.wait()
    await menu_actions[view.value](ctx, message)


async def settings_main(ctx: SnedSlashContext, message: t.Optional[hikari.Message] = None) -> None:
    """Show and handle settings main menu."""

    embed = hikari.Embed(
        title="Sned Configuration",
        description="""**Welcome to settings!**
        
        Here you can configure various aspects of the bot, such as moderation settings, automoderator, logging options, permissions, and more. 
        Click one of the buttons below to get started!""",
        color=ctx.app.embed_blue,
    )

    buttons = [
        OptionButton(label="Moderation"),
        OptionButton(label="Auto-Moderation"),
        OptionButton(label="Logging"),
        OptionButton(label="Reports"),
    ]

    view = ButtonMenuView(ctx, buttons, is_nested=False)
    ctx.parent = None
    if message:
        message = await helpers.maybe_edit(message, embed=embed, components=view.build())
        view.start(message)
    else:
        proxy = await ctx.respond(embed=embed, components=view.build())
        message = await proxy.message()
        view.start(message)

    await view.wait()
    await menu_actions[view.value](ctx, message)


async def settings_mod(ctx: SnedSlashContext, message: hikari.Message) -> None:
    """Show and handle Moderation menu."""

    mod = ctx.app.get_plugin("Moderation")
    mod_settings = await mod.d.actions.get_settings(ctx.guild_id)

    embed = hikari.Embed(
        title="Moderation Settings",
        description="Below you can see the current moderation settings, to change any of them, press the corresponding button!",
        color=ctx.app.embed_blue,
    )
    buttons = []
    for key, value in mod_settings.items():
        buttons.append(OptionButton(label=mod_settings_strings[key], style=hikari.ButtonStyle.SECONDARY))
        embed.add_field(name=mod_settings_strings[key], value=str(value), inline=True)

    view = ButtonMenuView(ctx, buttons=buttons, is_nested=True)
    ctx.parent = "Main"
    message = await helpers.maybe_edit(message, embed=embed, components=view.build())

    view.start(message)
    await view.wait()

    if view.value in menu_actions.keys():
        return await menu_actions[view.value](ctx, message)

    option = get_key(mod_settings_strings, view.value)

    await ctx.app.pool.execute(
        f"""
    INSERT INTO mod_config (guild_id, {option})
    VALUES ($1, $2)
    ON CONFLICT (guild_id) DO
    UPDATE SET {option} = $2""",
        ctx.guild_id,
        not mod_settings[option],
    )
    await ctx.app.db_cache.refresh(table="mod_config", guild_id=ctx.guild_id)

    await settings_mod(ctx, message)


async def settings_logging(ctx: SnedSlashContext, message: hikari.Message) -> None:
    """Show and handle Logging menu."""

    logging = ctx.app.get_plugin("Logging")

    log_channels = await logging.d.actions.get_log_channel_ids_view(ctx.guild_id)

    embed = hikari.Embed(
        title="Logging Settings",
        description="Below you can see a list of logging events and channels associated with them. To change where a certain event's logs should be sent, click on the corresponding button.",
        color=ctx.app.embed_blue,
    )

    perms = lightbulb.utils.permissions_for(ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id))
    if not (perms & hikari.Permissions.VIEW_AUDIT_LOG):
        embed.add_field(
            name="⚠️ Warning!",
            value=f"The bot currently has no permissions to view the audit logs! This will severely limit logging capabilities. Please consider enabling `View Audit Log` for the bot in your server's settings!",
            inline=False,
        )

    options = []

    for log_category, channel_id in log_channels.items():
        channel = ctx.app.cache.get_guild_channel(channel_id) if channel_id else None
        embed.add_field(
            name=f"{log_event_strings[log_category]}",
            value=channel.mention if channel else "*Not set*",
            inline=True,
        )
        options.append(miru.SelectOption(label=log_event_strings[log_category], value=log_category))

    view = SelectMenuView(ctx, options=options, placeholder="Select a logging category...", is_nested=True)
    is_color = await logging.d.actions.is_color_enabled(ctx.guild_id)
    view.add_item(BooleanButton(state=is_color, label="Color logs"))
    ctx.parent = "Main"

    message = await helpers.maybe_edit(message, embed=embed, components=view.build())
    view.start(message)
    await view.wait()

    if view.value in menu_actions.keys():
        return await menu_actions[view.value](ctx, message)

    if isinstance(view.value, tuple) and view.value[0] == "Color logs":
        await ctx.app.pool.execute(
            """UPDATE log_config SET color = $1 WHERE guild_id = $2""", view.value[1], ctx.guild_id
        )
        await ctx.app.db_cache.refresh(table="log_config", guild_id=ctx.guild_id)
        return await settings_logging(ctx, message)

    log_event = view.value

    options = []
    options.append(miru.SelectOption(label="Disable", value="disable", description="Stop logging this event."))

    for guild_id, channel in ctx.app.cache.get_guild_channels_view_for_guild(ctx.guild_id).items():
        if isinstance(channel, hikari.TextableGuildChannel):
            options.append(miru.SelectOption(label=f"#{channel.name}", value=channel.id))

    embed = hikari.Embed(
        title="Logging Settings",
        description=f"Please select a channel where the following event should be logged: `{log_event_strings[log_event]}`",
        color=ctx.app.embed_blue,
    )

    try:
        channel = await helpers.ask(
            ctx,
            options=options,
            return_type=hikari.TextableGuildChannel,
            embed_or_content=embed,
            placeholder="Select a channel...",
            ignore=["disable"],
            message=message,
        )
    except TypeError:
        embed = hikari.Embed(
            title="❌ Channel not found.",
            description="Unable to locate channel. Please type a channel mention or ID.",
            color=ctx.app.error_color,
        )
        return await error_view_handler(ctx, message, embed, "Logging")

    except asyncio.TimeoutError:
        await menu_actions["Quit"](ctx, message)
    else:
        channel_id = channel.id if channel != "disable" else None
        logging = ctx.app.get_plugin("Logging")
        await logging.d.actions.set_log_channel(log_event, ctx.guild_id, channel_id)

        await settings_logging(ctx, message)


async def settings_automod(ctx: SettingsContext, message: hikari.Message) -> None:

    automod = ctx.app.get_plugin("Auto-Moderation")

    assert automod is not None

    policies = await automod.d.actions.get_policies(ctx.guild_id)
    embed = hikari.Embed(
        title="Automoderation Settings",
        description="Below you can see a summary of the current automoderation settings. To see more details about a specific entry or change their settings, select it below!",
        color=ctx.app.embed_blue,
    )

    options = []
    for key in policies.keys():
        embed.add_field(
            name=policy_strings[key]["name"],
            value=policies[key]["state"].capitalize(),
            inline=True,
        )
        # TODO: Add emojies maybe?
        options.append(miru.SelectOption(label=policy_strings[key]["name"], value=key))

    ctx.parent = "Main"
    view = SelectMenuView(ctx, options=options, placeholder="Select a policy...", is_nested=True)
    message = await helpers.maybe_edit(message, embed=embed, components=view.build())
    view.start(message)
    await view.wait()

    if view.value in menu_actions:
        return await menu_actions[view.value](ctx, message)

    await settings_automod_policy(ctx, message, view.value)


async def settings_automod_policy(
    ctx: SettingsContext, message: hikari.Message, policy: t.Optional[str] = None
) -> None:

    if not policy:
        return await settings_automod(ctx, message)

    automod = ctx.app.get_plugin("Auto-Moderation")

    assert automod is not None

    policies: t.Dict[str, t.Any] = await automod.d.actions.get_policies(ctx.guild_id)
    policy_data = policies[policy]
    embed = hikari.Embed(
        title=f"Options for: {policy_strings[policy]['name']}",
        description=policy_strings[policy]["description"],
        color=ctx.app.embed_blue,
    )

    state = policy_data["state"]
    options = []

    if state == "disabled":
        embed.add_field(
            name="ℹ️ Disclaimer:",
            value="More configuration options will appear if you enable/change the state of this entry!",
            inline=False,
        )

    embed.add_field(name="State:", value=state.capitalize(), inline=False)
    options.append(miru.SelectOption(label="State", value="state"))

    # Conditions for certain attributes to appear
    predicates = {
        "temp_dur": lambda s: s in ["timeout", "tempban"],
    }

    if state != "disabled":
        for key in policy_data:
            if key == "state" or predicates.get(key) and not predicates[key](state):
                continue

            embed.add_field(
                name=policy_fields[key]["name"],
                value=policy_fields[key]["value"].format(value=policy_data[key]),
                inline=False,
            )
            options.append(miru.SelectOption(label=policy_fields[key]["label"], value=key))

    ctx.parent = "Auto-Moderation"
    view = SelectMenuView(
        ctx, options=options, placeholder="Select an entry to change...", is_nested=True, autodefer=False
    )
    message = await helpers.maybe_edit(message, embed=embed, components=view.build())
    view.start(message)
    await view.wait()

    if view.value in menu_actions:
        await ctx.last_inter.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
        return await menu_actions[view.value](ctx, message)

    sql = """
    INSERT INTO mod_config (automod_policies, guild_id)
    VALUES ($1, $2) 
    ON CONFLICT (guild_id) DO
    UPDATE SET automod_policies = $1"""

    # The option that is to be changed
    opt = view.value

    # Question types
    actions = {
        "boolean": ["delete"],
        "text_input": ["temp_dur", "words_list", "words_list_wildcard", "count"],
        "ask": ["excluded_channels", "excluded_roles"],
        "select": ["state"],
    }

    # Expected return type for a question
    expected_types = {
        "temp_dur": int,
        "words_list": str,
        "words_list_wildcard": str,
        "count": int,
        "excluded_channels": str,
        "excluded_roles": str,
    }

    responded = False
    action = [key for key in actions if opt in actions[key]][0]

    if opt == "state":  # State changing is a special case

        if not responded:
            await ctx.last_inter.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
            responded = True

        options = [
            miru.SelectOption(value=state, label=policy_states[state]["name"])
            for state in policy_states.keys()
            if policy not in policy_states[state]["excludes"]
        ]
        ctx.parent = "Auto-Moderation"
        view = SelectMenuView(ctx, options=options, placeholder="Select the state of this policy...", is_nested=True)
        embed = hikari.Embed(
            title="Select state...", description="Select a new state for this policy...", color=ctx.app.embed_blue
        )
        message = await helpers.maybe_edit(message, embed=embed, components=view.build())
        view.start(message)
        await view.wait()

        if view.value in menu_actions:
            return await menu_actions[view.value](ctx, message)

        policies[policy]["state"] = view.value
        await ctx.app.pool.execute(sql, json.dumps(policies), ctx.guild_id)
        await ctx.app.db_cache.refresh(table="mod_config", guild_id=ctx.guild_id)

    elif action == "boolean":
        policies[policy][opt] = not policies[policy][opt]
        await ctx.app.pool.execute(sql, json.dumps(policies), ctx.guild_id)
        await ctx.app.db_cache.refresh(table="mod_config", guild_id=ctx.guild_id)

    elif action == "text_input":
        embed = hikari.Embed(
            title=f"Editing {policy_fields[opt]['label']}...",
            description="A modal should have appeared for text input...\n\n*If you cancelled the modal, please re-execute the command!*",
            color=ctx.app.embed_blue,
        )

        modal = miru.Modal(f"Changing {policy_fields[opt]['label']}...")
        # Deepcopy because we store instances for convenience
        text_input = copy.deepcopy(policy_text_inputs[opt])
        # Prefill only bad words
        if opt in ["words_list", "words_list_wildcard"]:
            text_input.value = policies[policy][opt]
        modal.add_item(text_input)

        await modal.send(ctx.last_inter)
        responded = True
        await helpers.maybe_edit(message, embed=embed, components=[])
        await modal.wait()
        value = list(modal.values.values())[0]

        try:
            value = expected_types[opt](value)
            if isinstance(value, int):
                value = abs(value)

        except (TypeError, ValueError):  # String conversion shouldn't fail... right??
            embed = hikari.Embed(
                title="❌ Invalid Type",
                description=f"Expected a **number** for option `{policy_fields[opt]['label']}`.",
                color=ctx.app.error_color,
            )
            return await error_view_handler(ctx, message, embed, "Auto-Moderation")

        policies[policy][opt] = value
        await ctx.app.pool.execute(sql, json.dumps(policies), ctx.guild_id)
        await ctx.app.db_cache.refresh(table="mod_config", guild_id=ctx.guild_id)

    elif action == "ask":
        embed = hikari.Embed(
            title="❌ Not Implemented",
            description=f"Blame Hyper",
            color=ctx.app.error_color,
        )
        return await error_view_handler(ctx, message, embed, "Auto-Moderation")

    if not responded:
        # Only text inputs need the inter to create the modal, the rest can be safely deferred
        await ctx.last_inter.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
        responded = True

    await settings_automod_policy(ctx, message, policy)


async def settings_report(ctx: SettingsContext, message: hikari.Message) -> None:

    records = await ctx.app.db_cache.get(table="reports", guild_id=ctx.guild_id)
    if not records:
        records = [{"guild_id": ctx.guild_id, "is_enabled": False, "channel_id": None, "pinged_role_ids": None}]

    pinged_roles = (
        [ctx.app.cache.get_role(role_id) for role_id in records[0]["pinged_role_ids"]]
        if records[0]["pinged_role_ids"]
        else []
    )
    all_roles = list(ctx.app.cache.get_roles_view_for_guild(ctx.guild_id).values())
    unadded_roles = list(set(all_roles) - set(pinged_roles))

    channel = ctx.app.cache.get_guild_channel(records[0]["channel_id"]) if records[0]["channel_id"] else None

    embed = hikari.Embed(
        title="Reports Settings",
        description="Below you can see all settings for configuring the reporting of other users or messages. This allows other users to flag suspicious content for review.",
        color=ctx.app.embed_blue,
    )
    embed.add_field("Channel", value=channel.mention if channel else "*Not set*", inline=True)
    embed.add_field(name="​", value="​", inline=True)  # Spacer
    embed.add_field(
        "Pinged Roles", value=" ".join([role.mention for role in pinged_roles if role]) or "*None set*", inline=True
    )

    buttons = [
        BooleanButton(state=records[0]["is_enabled"] if channel else False, label="Enabled", disabled=not channel),
        OptionButton(label="Set Channel"),
        OptionButton(label="Add Role", disabled=not unadded_roles),
        OptionButton(label="Remove Role", disabled=not pinged_roles),
    ]

    ctx.parent = "Main"
    view = ButtonMenuView(ctx, buttons=buttons, is_nested=True)
    await helpers.maybe_edit(message, embed=embed, components=view.build())
    view.start(message)
    await view.wait()

    if view.value in menu_actions.keys():
        return await menu_actions[view.value](ctx, message)

    if isinstance(view.value, tuple) and view.value[0] == "Enabled":
        await ctx.app.pool.execute(
            """INSERT INTO reports (is_enabled, guild_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO
            UPDATE SET is_enabled = $1""",
            view.value[1],
            ctx.guild_id,
        )
        await ctx.app.db_cache.refresh(table="reports", guild_id=ctx.guild_id)
        return await settings_report(ctx, message)

    if view.value == "Set Channel":

        embed = hikari.Embed(
            title="Reports Settings",
            description=f"Please select a channel where reports will be sent.",
            color=ctx.app.embed_blue,
        )

        options = []
        for guild_id, channel in ctx.app.cache.get_guild_channels_view_for_guild(ctx.guild_id).items():
            if isinstance(channel, hikari.TextableGuildChannel):
                options.append(miru.SelectOption(label=f"#{channel.name}", value=channel.id))

        try:
            channel = await helpers.ask(
                ctx,
                options=options,
                return_type=hikari.TextableGuildChannel,
                embed_or_content=embed,
                placeholder="Select a channel...",
                message=message,
            )
        except TypeError:
            embed = hikari.Embed(
                title="❌ Channel not found.",
                description="Unable to locate channel. Please type a channel mention or ID.",
                color=ctx.app.error_color,
            )
            return await error_view_handler(ctx, message, embed, "Reports")

        except asyncio.TimeoutError:
            await menu_actions["Quit"](ctx, message)

        else:
            await ctx.app.pool.execute(
                """INSERT INTO reports (channel_id, guild_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO
            UPDATE SET channel_id = $1""",
                channel.id,
                ctx.guild_id,
            )
            await ctx.app.db_cache.refresh(table="reports", guild_id=ctx.guild_id)
            return await settings_report(ctx, message)

    if view.value == "Add Role":

        embed = hikari.Embed(
            title="Reports Settings",
            description=f"Select a role to add to the list of roles that will be mentioned when a new report is made.",
            color=ctx.app.embed_blue,
        )

        options = []
        for role in unadded_roles:
            options.append(miru.SelectOption(label=f"{role.name}", value=role.id))

        try:
            role = await helpers.ask(
                ctx,
                options=options,
                return_type=hikari.Role,
                embed_or_content=embed,
                placeholder="Select a role...",
                message=message,
            )
            pinged_roles.append(role)
        except TypeError:
            embed = hikari.Embed(
                title="❌ Role not found.",
                description="Unable to locate role. Please type a role mention or ID.",
                color=ctx.app.error_color,
            )
            return await error_view_handler(ctx, message, embed, "Reports")

        except asyncio.TimeoutError:
            await menu_actions["Quit"](ctx, message)

    elif view.value == "Remove Role":

        embed = hikari.Embed(
            title="Reports Settings",
            description=f"Remove a role from the list of roles that is mentioned when a new report is made.",
            color=ctx.app.embed_blue,
        )

        options = []
        for role in pinged_roles:
            options.append(miru.SelectOption(label=f"{role.name}", value=role.id))

        try:
            role = await helpers.ask(
                ctx,
                options=options,
                return_type=hikari.Role,
                embed_or_content=embed,
                placeholder="Select a role...",
                message=message,
            )
            if role in pinged_roles:
                pinged_roles.remove(role)
            else:
                raise TypeError

        except TypeError:
            embed = hikari.Embed(
                title="❌ Role not found.",
                description="Unable to locate role, or it is not a pinged role.",
                color=ctx.app.error_color,
            )
            return await error_view_handler(ctx, message, embed, "Reports")

        except asyncio.TimeoutError:
            await menu_actions["Quit"](ctx, message)

    await ctx.app.pool.execute(
        """INSERT INTO reports (pinged_role_ids, guild_id)
    VALUES ($1, $2)
    ON CONFLICT (guild_id) DO
    UPDATE SET pinged_role_ids = $1""",
        [role.id for role in pinged_roles],
        ctx.guild_id,
    )
    await ctx.app.db_cache.refresh(table="reports", guild_id=ctx.guild_id)
    await settings_report(ctx, message)


async def timeout_or_quit(ctx: SettingsContext, message: t.Optional[hikari.Message] = None) -> None:
    """
    Handle a timeout or quit request.
    """
    await helpers.maybe_delete(message)


async def back(ctx: SettingsContext, message: hikari.Message) -> None:
    """
    Get back to the previous menu, or quit if no parent is found.
    """
    if ctx.parent:
        await menu_actions[ctx.parent](ctx, message)


# Contains menu actions, buttons may reference this via their label
menu_actions = {
    "Main": settings_main,
    "Moderation": settings_mod,
    "Auto-Moderation": settings_automod,
    "Auto-Moderation Policy View": settings_automod_policy,
    "Logging": settings_logging,
    "Reports": settings_report,
    "Timeout": timeout_or_quit,
    "Quit": timeout_or_quit,
    "Back": back,
}


@settings.command()
@lightbulb.add_checks(
    lightbulb.bot_has_guild_permissions(hikari.Permissions.SEND_MESSAGES, hikari.Permissions.READ_MESSAGE_HISTORY)
)
@lightbulb.add_checks(lightbulb.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.command("settings", "Adjust different settings of the bot via an interactive menu.")
@lightbulb.implements(lightbulb.SlashCommand)
async def settings_cmd(ctx: SnedSlashContext) -> None:
    ctx = SettingsContext(ctx.app, ctx.event, ctx.command)
    await settings_main(ctx)  # Start menu, with initial message


def load(bot: SnedBot) -> None:
    bot.add_plugin(settings)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(settings)
