import asyncio
import logging

import hikari
import lightbulb
import miru
from models.bot import SnedBot
from utils import helpers
import models
from typing import Optional, List, Any

from etc.settings_static import *

logger = logging.getLogger(__name__)

settings = lightbulb.Plugin("Settings")


def get_key(dictionary: dict, value: Any) -> Any:
    """
    Get key from value in dict, too lazy to copy this garbage
    """
    return list(dictionary.keys())[list(dictionary.values()).index(value)]


class SettingsContext(lightbulb.SlashContext):
    """Abuse subclassing to get custom data into other functions c:"""

    def __init__(
        self, app: lightbulb.BotApp, event: hikari.InteractionCreateEvent, command: lightbulb.SlashCommand
    ) -> None:
        super().__init__(app, event, command)
        self.parent = None


# Settings Menu Views


class BooleanButton(miru.Button):
    """A boolean toggle button."""

    def __init__(self, *, state: bool, label: str = None, row: Optional[int] = None) -> None:
        style = hikari.ButtonStyle.SUCCESS if state else hikari.ButtonStyle.DANGER
        emoji = "✔️" if state else "✖️"

        self.state = state

        super().__init__(style=style, label=label, emoji=emoji, row=row)

    async def callback(self, context: miru.Context) -> None:
        self.state = not self.state

        self.style = hikari.ButtonStyle.SUCCESS if self.state else hikari.ButtonStyle.DANGER
        self.emoji = "✔️" if self.state else "✖️"
        self.view.value = (self.label, self.state)

        self.view.stop()


class OptionButton(miru.Button):
    """Button that sets view value to label, stops view."""

    async def callback(self, context: miru.Context) -> None:
        if not isinstance(self.view, MenuBaseView):
            return

        self.view.value = self.label
        self.view.stop()


class OptionsSelect(miru.Select):
    """Select that sets view value to first selected option's value."""

    async def callback(self, context: miru.Context) -> None:
        if not isinstance(self.view, MenuBaseView):
            return

        self.view.value = self.values[0]
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
        timeout: Optional[float] = 120,
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
        buttons: Optional[List[OptionButton]] = None,
        is_nested: bool = False,
        *,
        timeout: Optional[float] = 120,
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
        options: List[miru.SelectOption],
        placeholder: str,
        is_nested: bool = False,
        *,
        timeout: Optional[float] = 120,
        autodefer: bool = True,
    ) -> None:
        super().__init__(lctx, timeout=timeout, autodefer=autodefer)
        self.add_item(OptionsSelect(options=options, placeholder=placeholder))

        if is_nested:
            self.add_item(BackButton())
        else:
            self.add_item(QuitButton())


# Menu functions and handling


async def settings_main(ctx: lightbulb.SlashContext, message: Optional[hikari.Message] = None) -> None:
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


async def settings_mod(ctx: lightbulb.SlashContext, message: hikari.Message) -> None:
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


async def settings_automod(ctx: lightbulb.SlashContext, message: hikari.Message) -> None:
    """Show and handle Auto-Moderation menu."""
    pass  # TODO: Implement


async def settings_logging(ctx: lightbulb.SlashContext, message: hikari.Message) -> None:
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
        ctx.parent = "Logging"
        view = ButtonMenuView(ctx, is_nested=True)
        await helpers.maybe_edit(message, embed=embed, components=view.build())
        view.start(message)
        await view.wait()
        await menu_actions[view.value](ctx, message)

    except asyncio.TimeoutError:
        await menu_actions["Quit"](ctx, message)
    else:
        channel_id = channel.id if channel != "disable" else None
        logging = ctx.app.get_plugin("Logging")
        await logging.d.actions.set_log_channel(log_event, ctx.guild_id, channel_id)

        await settings_logging(ctx, message)


async def timeout_or_quit(ctx: SettingsContext, message: Optional[hikari.Message] = None) -> None:
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
    "Logging": settings_logging,
    "Timeout": timeout_or_quit,
    "Quit": timeout_or_quit,
    "Back": back,
}


@settings.command()
@lightbulb.command("settings", "Adjust different settings of the bot via an interactive menu.")
@lightbulb.implements(lightbulb.SlashCommand)
async def settings_cmd(ctx: lightbulb.SlashContext) -> None:
    ctx = SettingsContext(ctx.app, ctx.event, ctx.command)
    await settings_main(ctx)  # Start menu, with initial message


def load(bot: SnedBot) -> None:
    bot.add_plugin(settings)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(settings)
