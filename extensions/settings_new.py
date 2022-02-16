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
from lightbulb.utils.parser import CONVERTER_TYPE_MAPPING
from miru.abc import *
from models.bot import SnedBot
from models.components import *
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
    """God objects go brr >_<"""

    def __init__(self, lctx: lightbulb.Context, *, timeout: t.Optional[float] = 300, autodefer: bool = False) -> None:
        super().__init__(lctx, timeout=timeout, autodefer=autodefer)

        # Last received context object
        self.last_ctx: t.Optional[t.Union[miru.Context, SnedContext]] = lctx

        self.value: str = None
        self.ephemeral: bool = False
        self.flags = hikari.MessageFlag.EPHEMERAL if self.ephemeral else hikari.UNDEFINED
        self.input_event: asyncio.Event = asyncio.Event()

        # Mapping of custom_id, menu action
        self.menu_actions = {
            "Main": self.settings_main,
            "Reports": self.settings_report,
            "Quit": self.quit_settings,
        }

    # Transitions
    def add_buttons(self, buttons: t.Sequence[miru.Button], parent: t.Optional[str] = None) -> None:
        """Add a new set of buttons, clearing previous components."""
        self.clear_items()

        if parent:
            self.add_item(BackButton(parent))
        else:
            self.add_item(QuitButton())

        for button in buttons:
            self.add_item(button)

    def select_screen(self, select: miru.Select, parent: t.Optional[str] = None) -> None:
        """Set view to a new select screen, clearing previous components."""
        self.clear_items()

        self.add_item(select)

        if parent:
            self.add_item(BackButton(parent))
        else:
            self.add_item(QuitButton())

    async def on_timeout(self) -> None:
        """Stop waiting for input events after the view times out."""
        self.input_event.set()

    async def wait_for_input(self) -> None:
        """Wait until a user input is given, then reset the event."""
        self.input_event.clear()
        await self.input_event.wait()

        if self._stopped.is_set():  # FIXME this is crap
            raise asyncio.CancelledError

    async def quit_settings(self) -> None:
        """Exit settings menu."""
        try:
            await self.last_ctx.defer()
        except RuntimeError:
            pass

        if self.ephemeral:
            return

        await helpers.maybe_delete(self.last_ctx.message)
        self.stop()

    async def start_settings(self) -> None:
        await self.settings_main(initial=True)

    async def settings_main(self, initial: bool = False) -> None:
        """Show and handle settings main menu."""

        embed = hikari.Embed(
            title="Sned Configuration",
            description="""**Welcome to settings!**
            
            Here you can configure various aspects of the bot, such as moderation settings, automoderator, logging options, permissions, and more. 
            Click one of the buttons below to get started!""",
            color=self.app.embed_blue,
        )

        buttons = [
            OptionButton(label="Moderation"),
            OptionButton(label="Auto-Moderation"),
            OptionButton(label="Logging"),
            OptionButton(label="Reports"),
        ]

        self.add_buttons(buttons)
        if initial:
            resp = await self.last_ctx.respond(embed=embed, components=self.build())
            message = await resp.message()
            self.start(message)
        else:
            await self.last_ctx.edit_response(embed=embed, components=self.build())

        await self.wait_for_input()
        await self.menu_actions[self.value]()

    async def settings_report(self) -> None:
        """The reports menu."""

        records = await self.app.db_cache.get(table="reports", guild_id=self.last_ctx.guild_id)

        if not records:
            records = [
                {"guild_id": self.last_ctx.guild_id, "is_enabled": False, "channel_id": None, "pinged_role_ids": None}
            ]

        pinged_roles = (
            [self.app.cache.get_role(role_id) for role_id in records[0]["pinged_role_ids"]]
            if records[0]["pinged_role_ids"]
            else []
        )
        all_roles = list(self.app.cache.get_roles_view_for_guild(self.last_ctx.guild_id).values())
        unadded_roles = list(set(all_roles) - set(pinged_roles))

        channel = self.app.cache.get_guild_channel(records[0]["channel_id"]) if records[0]["channel_id"] else None

        embed = hikari.Embed(
            title="Reports Settings",
            description="Below you can see all settings for configuring the reporting of other users or messages. This allows other users to flag suspicious content for review.",
            color=self.app.embed_blue,
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
        self.add_buttons(buttons, parent="Main")
        await self.last_ctx.edit_response(embed=embed, components=self.build())
        await self.wait_for_input()

        if not self.value:
            return

        if isinstance(self.value, tuple) and self.value[0] == "Enabled":
            await self.app.pool.execute(
                """INSERT INTO reports (is_enabled, guild_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO
                UPDATE SET is_enabled = $1""",
                self.value[1],
                self.last_ctx.guild_id,
            )
            await self.app.db_cache.refresh(table="reports", guild_id=self.last_ctx.guild_id)
            return await self.settings_report()

        if self.value == "Set Channel":
            embed = hikari.Embed(
                title="Reports Settings",
                description=f"Please select a channel where reports will be sent.",
                color=self.app.embed_blue,
            )

            options = []
            for channel in self.app.cache.get_guild_channels_view_for_guild(self.last_ctx.guild_id).values():
                if isinstance(channel, hikari.TextableGuildChannel):
                    options.append(miru.SelectOption(label=f"#{channel.name}", value=channel.id))

            try:
                channel = await ask_settings(
                    self,
                    self.last_ctx,
                    options=options,
                    return_type=hikari.TextableGuildChannel,
                    embed_or_content=embed,
                    placeholder="Select a channel...",
                )
            except TypeError:
                embed = hikari.Embed(
                    title="❌ Channel not found.",
                    description="Unable to locate channel. Please type a channel mention or ID.",
                    color=self.app.error_color,
                )
                self.add_buttons([BackButton("Reports")])
                await self.wait_for_input()
                await self.last_ctx.edit_response(embed=embed, components=self.build())

            except asyncio.TimeoutError:
                await self.quit_settings()

            else:
                await self.app.pool.execute(
                    """INSERT INTO reports (channel_id, guild_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO
                UPDATE SET channel_id = $1""",
                    channel.id,
                    self.last_ctx.guild_id,
                )
            await self.app.db_cache.refresh(table="reports", guild_id=self.last_ctx.guild_id)
            return await self.settings_report()

        if self.value == "Add Role":

            embed = hikari.Embed(
                title="Reports Settings",
                description="Select a role to add to the list of roles that will be mentioned when a new report is made.",
                color=self.last_ctx.app.embed_blue,
            )

            options = []
            for role in unadded_roles:
                options.append(miru.SelectOption(label=f"{role.name}", value=role.id))

            try:
                role = await ask_settings(
                    self,
                    self.last_ctx,
                    options=options,
                    return_type=hikari.Role,
                    embed_or_content=embed,
                    placeholder="Select a role...",
                )
                pinged_roles.append(role)
            except TypeError:
                embed = hikari.Embed(
                    title="❌ Role not found.",
                    description="Unable to locate role. Please type a role mention or ID.",
                    color=self.last_ctx.app.error_color,
                )
                self.add_buttons([BackButton("Reports")])
                await self.wait_for_input()
                return await self.last_ctx.edit_response(embed=embed, components=self.build())

            except asyncio.TimeoutError:
                return await self.quit_settings()

        elif self.value == "Remove Role":

            embed = hikari.Embed(
                title="Reports Settings",
                description="Remove a role from the list of roles that is mentioned when a new report is made.",
                color=self.last_ctx.app.embed_blue,
            )

            options = []
            for role in pinged_roles:
                options.append(miru.SelectOption(label=f"{role.name}", value=role.id))

            try:
                role = await ask_settings(
                    self,
                    self.last_ctx,
                    options=options,
                    return_type=hikari.Role,
                    embed_or_content=embed,
                    placeholder="Select a role...",
                )
                if role in pinged_roles:
                    pinged_roles.remove(role)
                else:
                    raise TypeError

            except TypeError:
                embed = hikari.Embed(
                    title="❌ Role not found.",
                    description="Unable to locate role. Please type a role mention or ID.",
                    color=self.last_ctx.app.error_color,
                )
                self.add_buttons([BackButton("Reports")])
                await self.wait_for_input()
                return await self.last_ctx.edit_response(embed=embed, components=self.build())

            except asyncio.TimeoutError:
                return await self.quit_settings()

        await self.app.pool.execute(
            """INSERT INTO reports (pinged_role_ids, guild_id)
        VALUES ($1, $2)
        ON CONFLICT (guild_id) DO
        UPDATE SET pinged_role_ids = $1""",
            [role.id for role in pinged_roles],
            self.last_ctx.guild_id,
        )

        await self.app.db_cache.refresh(table="reports", guild_id=self.last_ctx.guild_id)
        await self.settings_report()


T = t.TypeVar("T")


async def ask_settings(
    view: SettingsView,
    ctx: miru.Context,
    *,
    options: t.List[miru.SelectOption],
    return_type: T,
    embed_or_content: t.Union[str, hikari.Embed],
    placeholder: str = None,
    ignore: t.Optional[t.List[t.Any]] = None,
    ephemeral: bool = False,
) -> t.Union[T, t.Any]:
    """Ask a question from the user, while taking into account the select menu limitations.

    Parameters
    ----------
    view : SettingsView
        The view to interact with and return interactions to.
    ctx : miru.Context
        The last context object seen by the view.
    options : t.List[miru.SelectOption]
        The list of options to present to the user.
    return_type : T
        The expected return type.
    embed_or_content : t.Union[str, hikari.Embed]
        The content or attached embed of the message to send.
    placeholder : str, optional
        The placeholder text on the select menu, by default None
    ignore : t.Optional[t.List[t.Any]], optional
        Values that will not be converted and returned directly, by default None
    ephemeral : bool, optional
        If the query should be done ephemerally, by default False

    Returns
    -------
    t.Union[T, t.Any]
        Returns T unless it is in ignore.

    Raises
    ------
    TypeError
        embed_or_content was not of type str or hikari.Embed
    asyncio.TimeoutError
        The query exceeded the given timeout.
    """

    if return_type not in CONVERTER_TYPE_MAPPING.keys():
        return TypeError(
            f"return_type must be of types: {' '.join(list(CONVERTER_TYPE_MAPPING.keys()))}, not {return_type}"
        )

    # Get appropiate converter for return type
    converter: lightbulb.BaseConverter = CONVERTER_TYPE_MAPPING[return_type](view.lctx)
    flags = hikari.MessageFlag.EPHEMERAL if ephemeral else hikari.UNDEFINED

    # If the select will result in a Bad Request or not
    invalid_select: bool = False
    if len(options) > 25:
        invalid_select = True
    else:
        for option in options:
            if len(option.label) > 100 or (option.description and len(option.description) > 100):
                invalid_select = True

    if isinstance(embed_or_content, str):
        content = embed_or_content
        embeds = []
    elif isinstance(embed_or_content, hikari.Embed):
        content = ""
        embeds = [embed_or_content]
    else:
        raise TypeError(f"embed_or_content must be of type str or hikari.Embed, not {type(embed_or_content)}")

    if not invalid_select:
        view.clear_items()
        view.add_item(OptionsSelect(placeholder=placeholder, options=options))
        await ctx.edit_response(content=content, embeds=embeds, components=view.build(), flags=flags)
        await view.wait_for_input()

        if view.value:
            if ignore and view.value in ignore:
                return view.value
            return await converter.convert(view.value)

        raise asyncio.TimeoutError("View timed out without response.")

    else:
        await ctx.defer(flags=flags)
        if embeds:
            embeds[0].description = f"{embeds[0].description}\n\nPlease type your response below!"
        elif content:
            content = f"{content}\n\nPlease type your response below!"

        await ctx.edit_response(content=content, embeds=embeds, components=[], flags=flags)

        predicate = lambda e: e.author_id == ctx.author.id and e.channel_id == ctx.channel_id

        event = await ctx.app.wait_for(hikari.MessageCreateEvent, timeout=300.0, predicate=predicate)
        if event.content:
            if ignore and event.content in ignore:
                return event.content
            return await converter.convert(event.content)


@settings.command()
@lightbulb.add_checks(
    lightbulb.bot_has_guild_permissions(hikari.Permissions.SEND_MESSAGES, hikari.Permissions.READ_MESSAGE_HISTORY)
)
@lightbulb.add_checks(lightbulb.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.command("settings", "Adjust different settings of the bot via an interactive menu.")
@lightbulb.implements(lightbulb.SlashCommand)
async def settings_cmd(ctx: SnedSlashContext) -> None:
    view = SettingsView(ctx, timeout=300)
    await view.start_settings()


def load(bot: SnedBot) -> None:
    bot.add_plugin(settings)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(settings)
