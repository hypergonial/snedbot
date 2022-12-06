import asyncio
import copy
import json
import logging
import typing as t

import hikari
import lightbulb
import miru
from lightbulb.utils.parser import CONVERTER_TYPE_MAPPING

import models
from etc import const
from etc.settings_static import *
from models.bot import SnedBot
from models.checks import bot_has_permissions, has_permissions
from models.components import *
from models.context import SnedSlashContext
from models.mod_actions import ModerationFlags
from models.plugin import SnedPlugin
from utils import helpers

logger = logging.getLogger(__name__)

settings = SnedPlugin("Settings")


def get_key(dictionary: dict, value: t.Any) -> t.Any:
    """
    Get key from value in dict, too lazy to copy this garbage
    """
    return list(dictionary.keys())[list(dictionary.values()).index(value)]


class SettingsView(models.AuthorOnlyView):
    """God objects go brr >_<"""

    def __init__(
        self,
        lctx: lightbulb.Context,
        *,
        timeout: t.Optional[float] = 300,
        ephemeral: bool = False,
        autodefer: bool = False,
    ) -> None:
        super().__init__(lctx, timeout=timeout, autodefer=autodefer)

        # Last received context object
        self.last_ctx: t.Optional[miru.Context] = None
        # Last component interacted with
        self.last_item: t.Optional[miru.Item] = None

        # Last value received as input
        self.value: t.Optional[str] = None
        # If True, provides the menu ephemerally
        self.ephemeral: bool = ephemeral

        self.flags = hikari.MessageFlag.EPHEMERAL if self.ephemeral else hikari.MessageFlag.NONE
        self.input_event: asyncio.Event = asyncio.Event()

        # Mapping of custom_id/label, menu action
        self.menu_actions = {
            "Main": self.settings_main,
            "Reports": self.settings_report,
            "Moderation": self.settings_mod,
            "Auto-Moderation": self.settings_automod,
            "Auto-Moderation Policies": self.settings_automod_policy,
            "Logging": self.settings_logging,
            "Starboard": self.settings_starboard,
            "Quit": self.quit_settings,
        }

    # Transitions
    def add_buttons(self, buttons: t.Sequence[miru.Button], parent: t.Optional[str] = None, **kwargs) -> None:
        """Add a new set of buttons, clearing previous components."""
        self.clear_items()

        if parent:
            self.add_item(BackButton(parent, **kwargs))
        else:
            self.add_item(QuitButton())

        for button in buttons:
            self.add_item(button)

    def select_screen(self, select: OptionsSelect, parent: t.Optional[str] = None, **kwargs) -> None:
        """Set view to a new select screen, clearing previous components."""
        self.clear_items()

        if not isinstance(select, OptionsSelect):
            logging.warning("Stop being an idiot, pass an OptionSelect, thx c:")

        self.add_item(select)

        if parent:
            self.add_item(BackButton(parent))
        else:
            self.add_item(QuitButton())

    async def error_screen(self, embed: hikari.Embed, parent: str, **kwargs) -> None:
        """
        Show an error screen with only a back button, and wait for input on it.
        """
        assert self.last_ctx is not None
        self.clear_items()
        self.add_item(BackButton(parent=parent, **kwargs))
        await self.last_ctx.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

    async def on_timeout(self) -> None:
        """Stop waiting for input events after the view times out."""
        self.value = None
        self.input_event.set()

        if not self.last_ctx:
            return

        for item in self.children:
            assert isinstance(item, (miru.Button, miru.Select))
            item.disabled = True

        try:
            await self.last_ctx.edit_response(components=self, flags=self.flags)
        except hikari.NotFoundError:
            pass

    """ async def wait_for_input(self) -> None:
        Wait until a user input is given, then reset the event.
        Other functions should check if view.value is None and return if so after waiting for this event.
        self.input_event.clear()
        await self.input_event.wait()

        if self._stopped.is_set():
            raise asyncio.CancelledError """

    async def quit_settings(self) -> None:
        """Exit settings menu."""

        assert self.last_ctx is not None
        for item in self.children:
            assert isinstance(item, (miru.Button, miru.Select))
            item.disabled = True

        try:
            await self.last_ctx.edit_response(components=self, flags=self.flags)
        except hikari.NotFoundError:
            pass

        self.value = None
        self.stop()
        self.input_event.set()

    async def start_settings(self) -> None:
        await self.settings_main(initial=True)

    async def settings_main(self, initial: bool = False) -> None:
        """Show and handle settings main menu."""

        embed = hikari.Embed(
            title="Sned Configuration",
            description="""**Welcome to settings!**

Here you can configure various aspects of the bot, such as moderation settings, automod, logging options, and more. 

Click one of the buttons below to get started!""",
            color=const.EMBED_BLUE,
        )

        buttons = [
            OptionButton(label="Moderation", emoji=const.EMOJI_MOD_SHIELD),
            OptionButton(label="Auto-Moderation", emoji="🤖"),
            OptionButton(label="Logging", emoji="🗒️"),
            OptionButton(label="Reports", emoji="📣", row=1),
            OptionButton(label="Starboard", emoji="⭐", row=1),
        ]

        self.add_buttons(buttons)
        if initial:
            resp = await self.lctx.respond(embed=embed, components=self, flags=self.flags)
            message = await resp.message()
            await self.start(message)
        else:
            assert self.last_ctx is not None
            await self.last_ctx.edit_response(embed=embed, components=self, flags=self.flags)

        await self.wait_for_input()
        if self.value is None:
            return

        await self.menu_actions[self.value]()

    async def settings_report(self) -> None:
        """The reports menu."""
        assert isinstance(self.app, SnedBot) and self.last_ctx is not None and self.last_ctx.guild_id is not None

        records = await self.app.db_cache.get(table="reports", guild_id=self.last_ctx.guild_id, limit=1)

        if not records:
            records = [
                {"guild_id": self.last_ctx.guild_id, "is_enabled": False, "channel_id": None, "pinged_role_ids": None}
            ]

        pinged_roles = (
            [self.app.cache.get_role(role_id) for role_id in records[0]["pinged_role_ids"]]
            if records[0]["pinged_role_ids"]
            else []
        )
        all_roles = [
            role
            for role in list(self.app.cache.get_roles_view_for_guild(self.last_ctx.guild_id).values())
            if role.id != self.last_ctx.guild_id
        ]
        unadded_roles = list(set(all_roles) - set(pinged_roles))

        channel = self.app.cache.get_guild_channel(records[0]["channel_id"]) if records[0]["channel_id"] else None

        embed = hikari.Embed(
            title="Reports Settings",
            description="Below you can see all settings for configuring the reporting of other users or messages. This allows other users to flag suspicious content for review.",
            color=const.EMBED_BLUE,
        )
        embed.add_field("Channel", value=channel.mention if channel else "*Not set*", inline=True)
        embed.add_field(name="​", value="​", inline=True)  # Spacer
        embed.add_field(
            "Pinged Roles", value=" ".join([role.mention for role in pinged_roles if role]) or "*None set*", inline=True
        )

        buttons = [
            BooleanButton(state=records[0]["is_enabled"] if channel else False, label="Enable", disabled=not channel),
            OptionButton(label="Set Channel", emoji=const.EMOJI_CHANNEL, style=hikari.ButtonStyle.SECONDARY),
            OptionButton(
                label="Role", disabled=not unadded_roles, custom_id="add_r", emoji="➕", style=hikari.ButtonStyle.SUCCESS
            ),
            OptionButton(
                label="Role", disabled=not pinged_roles, custom_id="del_r", emoji="➖", style=hikari.ButtonStyle.DANGER
            ),
        ]
        self.add_buttons(buttons, parent="Main")
        await self.last_ctx.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value:
            return

        if isinstance(self.value, tuple) and self.value[0] == "Enable":
            await self.app.db.execute(
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
                color=const.EMBED_BLUE,
            )

            options = [
                miru.SelectOption(label=channel.name, value=channel.id, emoji=const.EMOJI_CHANNEL)  # type: ignore
                for channel in self.app.cache.get_guild_channels_view_for_guild(self.last_ctx.guild_id).values()
                if isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel))
            ]

            try:
                channel = await ask_settings(
                    self,
                    self.last_ctx,
                    options=options,
                    return_type=hikari.TextableGuildChannel,
                    embed_or_content=embed,
                    placeholder="Select a channel...",
                    ephemeral=self.ephemeral,
                )
            except TypeError:
                embed = hikari.Embed(
                    title="❌ Channel not found.",
                    description="Unable to locate channel. Please type a channel mention or ID.",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Reports")

            else:
                await self.app.db.execute(
                    """INSERT INTO reports (channel_id, guild_id)
                    VALUES ($1, $2)
                    ON CONFLICT (guild_id) DO
                    UPDATE SET channel_id = $1""",
                    channel.id,
                    self.last_ctx.guild_id,
                )
            await self.app.db_cache.refresh(table="reports", guild_id=self.last_ctx.guild_id)
            return await self.settings_report()

        assert self.last_item and self.last_item.custom_id

        if self.last_item.custom_id == "add_r":

            embed = hikari.Embed(
                title="Reports Settings",
                description="Select a role to add to the list of roles that will be mentioned when a new report is made.",
                color=const.EMBED_BLUE,
            )

            options = [
                miru.SelectOption(label=role.name, value=str(role.id), emoji=const.EMOJI_MENTION)
                for role in unadded_roles
            ]

            try:
                role = await ask_settings(
                    self,
                    self.last_ctx,
                    options=options,
                    return_type=hikari.Role,
                    embed_or_content=embed,
                    placeholder="Select a role...",
                    ephemeral=self.ephemeral,
                )
                assert isinstance(role, hikari.Role)
                if role not in pinged_roles:
                    pinged_roles.append(role)
            except TypeError:
                embed = hikari.Embed(
                    title="❌ Role not found.",
                    description="Unable to locate role. Please type a role mention or ID.",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Reports")

        elif self.last_item.custom_id == "del_r":

            embed = hikari.Embed(
                title="Reports Settings",
                description="Remove a role from the list of roles that is mentioned when a new report is made.",
                color=const.EMBED_BLUE,
            )

            options = [
                miru.SelectOption(label=role.name, value=str(role.id), emoji=const.EMOJI_MENTION)
                for role in pinged_roles
                if role is not None
            ]

            try:
                role = await ask_settings(
                    self,
                    self.last_ctx,
                    options=options,
                    return_type=hikari.Role,
                    embed_or_content=embed,
                    placeholder="Select a role...",
                    ephemeral=self.ephemeral,
                )
                if role in pinged_roles:
                    assert isinstance(role, hikari.Role)
                    pinged_roles.remove(role)
                else:
                    raise TypeError

            except TypeError:
                embed = hikari.Embed(
                    title="❌ Role not found.",
                    description="Unable to locate role. Please type a role mention or ID.",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Reports")

        await self.app.db.execute(
            """INSERT INTO reports (pinged_role_ids, guild_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO
            UPDATE SET pinged_role_ids = $1""",
            [role.id for role in pinged_roles if role is not None],
            self.last_ctx.guild_id,
        )

        await self.app.db_cache.refresh(table="reports", guild_id=self.last_ctx.guild_id)
        await self.settings_report()

    async def settings_mod(self) -> None:
        """Show and handle Moderation menu."""
        assert isinstance(self.app, SnedBot) and self.last_ctx is not None and self.last_ctx.guild_id is not None

        mod_settings = await self.app.mod.get_settings(self.last_ctx.guild_id)

        embed = hikari.Embed(
            title="Moderation Settings",
            description="""Below you can see the current moderation settings, to change any of them, press the corresponding button!

Enabling the DM-ing of users will notify them in a direct message when they are punished through any of Sned's moderation commands or auto-moderation.
This does not apply to manually punishing them through Discord built-in commands/tools.

Enabling **ephemeral responses** will show all moderation command responses in a manner where they will be invisible to every user except for the one who used the command.""",
            color=const.EMBED_BLUE,
        )
        buttons = []
        for flag in ModerationFlags:
            if flag is ModerationFlags.NONE:
                continue

            value = bool(mod_settings.flags & flag)

            buttons.append(BooleanButton(state=value, label=mod_flags_strings[flag], custom_id=str(flag.value)))
            embed.add_field(name=mod_flags_strings[flag], value=str(value), inline=True)

        self.add_buttons(buttons, parent="Main")
        await self.last_ctx.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value:
            return

        assert self.last_item and self.last_item.custom_id
        flag = ModerationFlags(int(self.last_item.custom_id))

        await self.app.db.execute(
            f"""
            INSERT INTO mod_config (guild_id, flags)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO
            UPDATE SET flags = $2""",
            self.last_ctx.guild_id,
            (mod_settings.flags & ~flag).value if flag & mod_settings.flags else (mod_settings.flags | flag).value,
        )
        await self.app.db_cache.refresh(table="mod_config", guild_id=self.last_ctx.guild_id)

        await self.settings_mod()

    async def settings_starboard(self) -> None:

        assert isinstance(self.app, SnedBot) and self.last_ctx is not None and self.last_ctx.guild_id is not None

        records = await self.app.db_cache.get(table="starboard", guild_id=self.last_ctx.guild_id, limit=1)
        settings = (
            records[0]
            if records
            else {"is_enabled": False, "channel_id": None, "star_limit": 5, "excluded_channels": []}
        )

        starboard_channel = self.app.cache.get_guild_channel(settings["channel_id"]) if settings["channel_id"] else None
        is_enabled = settings["is_enabled"] if settings["channel_id"] else False

        excluded_channels = (
            [self.app.cache.get_guild_channel(channel_id) for channel_id in settings["excluded_channels"]]
            if settings["excluded_channels"]
            else []
        )
        all_channels = [
            channel
            for channel in self.app.cache.get_guild_channels_view_for_guild(self.last_ctx.guild_id).values()
            if isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel))
        ]
        included_channels = list(set(all_channels) - set(excluded_channels))  # type: ignore

        embed = hikari.Embed(
            title="Starboard Settings",
            description="Below you can see the current settings for this server's starboard! If enabled, users can star messages by reacting with ⭐, and if the number of reactions reaches the specified limit, the message will be sent into the specified starboard channel.",
            color=const.EMBED_BLUE,
        )
        buttons = [
            BooleanButton(state=is_enabled, label="Enable", disabled=not starboard_channel),
            OptionButton(style=hikari.ButtonStyle.SECONDARY, label="Set Channel", emoji=const.EMOJI_CHANNEL),
            OptionButton(style=hikari.ButtonStyle.SECONDARY, label="Limit", emoji="⭐"),
            OptionButton(
                style=hikari.ButtonStyle.SUCCESS,
                label="Excluded",
                emoji="➕",
                row=1,
                custom_id="add_excluded",
                disabled=not included_channels,
            ),
            OptionButton(
                style=hikari.ButtonStyle.DANGER,
                label="Excluded",
                emoji="➖",
                row=1,
                custom_id="del_excluded",
                disabled=not excluded_channels,
            ),
        ]
        embed.add_field(
            "Starboard Channel", starboard_channel.mention if starboard_channel else "*Not set*", inline=True
        )
        embed.add_field("Star Limit", settings["star_limit"], inline=True)
        embed.add_field(
            "Excluded Channels",
            " ".join([channel.mention for channel in excluded_channels if channel])[:512]
            if excluded_channels
            else "*Not set*",
            inline=True,
        )
        self.add_buttons(buttons, parent="Main")
        await self.last_ctx.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if self.value is None:
            return

        if isinstance(self.value, tuple) and self.value[0] == "Enable":
            await self.app.db.execute(
                """INSERT INTO starboard (is_enabled, guild_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO
                UPDATE SET is_enabled = $1""",
                self.value[1],
                self.last_ctx.guild_id,
            )
            await self.app.db_cache.refresh(table="starboard", guild_id=self.last_ctx.guild_id)
            return await self.settings_starboard()

        if self.value == "Limit":
            modal = OptionsModal(self, title="Changing star limit...")
            modal.add_item(
                miru.TextInput(
                    label="Star Limit",
                    required=True,
                    max_length=3,
                    value=settings["star_limit"],
                    placeholder="Enter a positive integer to be set as the minimum required amount of stars...",
                )
            )
            assert isinstance(self.last_ctx, miru.ViewContext)
            await self.last_ctx.respond_with_modal(modal)
            await self.wait_for_input()

            if not self.value:
                return

            assert isinstance(self.value, dict)
            limit = list(self.value.values())[0]

            try:
                limit = abs(int(limit))
                if limit == 0:
                    raise ValueError

            except (TypeError, ValueError):
                embed = hikari.Embed(
                    title="❌ Invalid Type",
                    description=f"Expected a non-zero **number**.",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Starboard")

            await self.app.db.execute(
                """INSERT INTO starboard (star_limit, guild_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO
                UPDATE SET star_limit = $1""",
                limit,
                self.last_ctx.guild_id,
            )
            await self.app.db_cache.refresh(table="starboard", guild_id=self.last_ctx.guild_id)
            return await self.settings_starboard()

        if self.value == "Set Channel":
            embed = hikari.Embed(
                title="Starboard Settings",
                description=f"Please select a channel where starred messages will be sent.",
                color=const.EMBED_BLUE,
            )

            options = [
                miru.SelectOption(label=str(channel.name), value=str(channel.id), emoji=const.EMOJI_CHANNEL)
                for channel in all_channels
            ]

            try:
                channel = await ask_settings(
                    self,
                    self.last_ctx,
                    options=options,
                    return_type=hikari.TextableGuildChannel,
                    embed_or_content=embed,
                    placeholder="Select a channel...",
                    ephemeral=self.ephemeral,
                )
            except TypeError:
                embed = hikari.Embed(
                    title="❌ Channel not found.",
                    description="Unable to locate channel. Please type a channel mention or ID.",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Starboard")
            else:
                await self.app.db.execute(
                    """INSERT INTO starboard (channel_id, guild_id)
                    VALUES ($1, $2)
                    ON CONFLICT (guild_id) DO
                    UPDATE SET channel_id = $1""",
                    channel.id if channel else None,
                    self.last_ctx.guild_id,
                )
            await self.app.db_cache.refresh(table="starboard", guild_id=self.last_ctx.guild_id)
            return await self.settings_starboard()

        assert self.last_item is not None
        if self.last_item.custom_id == "add_excluded":

            embed = hikari.Embed(
                title="Starboard Settings",
                description="Select a new channel to be added to the list of excluded channels. Users will not be able to star messages from these channels.",
                color=const.EMBED_BLUE,
            )

            options = [
                miru.SelectOption(label=channel.name, value=channel.id, emoji=const.EMOJI_CHANNEL)
                for channel in included_channels
            ]

            try:
                channel = await ask_settings(
                    self,
                    self.last_ctx,
                    options=options,
                    return_type=hikari.TextableGuildChannel,
                    embed_or_content=embed,
                    placeholder="Select a channel...",
                    ephemeral=self.ephemeral,
                )
                assert isinstance(channel, hikari.TextableGuildChannel)
                if channel and channel not in excluded_channels:
                    excluded_channels.append(channel)
            except TypeError:
                embed = hikari.Embed(
                    title="❌ Channel not found.",
                    description="Unable to locate channel. Please type a channel mention or ID.",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Starboard")

        elif self.last_item.custom_id == "del_excluded":

            embed = hikari.Embed(
                title="Starboard Settings",
                description="Remove a channel from the list of excluded channels.",
                color=const.EMBED_BLUE,
            )

            options = [
                miru.SelectOption(label=str(channel.name), value=str(channel.id), emoji=const.EMOJI_CHANNEL)
                for channel in excluded_channels
                if channel
            ]

            try:
                channel = await ask_settings(
                    self,
                    self.last_ctx,
                    options=options,
                    return_type=hikari.TextableGuildChannel,
                    embed_or_content=embed,
                    placeholder="Select a channel...",
                    ephemeral=self.ephemeral,
                )
                if channel and channel in excluded_channels:
                    assert isinstance(channel, hikari.TextableGuildChannel)
                    excluded_channels.remove(channel)
                else:
                    raise TypeError

            except TypeError:
                embed = hikari.Embed(
                    title="❌ Channel not found.",
                    description="Unable to locate channel. Please type a channel mention or ID.",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Starboard")

        await self.app.db.execute(
            """INSERT INTO starboard (excluded_channels, guild_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO
            UPDATE SET excluded_channels = $1""",
            [channel.id for channel in excluded_channels if channel],
            self.last_ctx.guild_id,
        )

        await self.app.db_cache.refresh(table="starboard", guild_id=self.last_ctx.guild_id)
        await self.settings_starboard()

    async def settings_logging(self) -> None:
        """Show and handle Logging menu."""

        assert isinstance(self.app, SnedBot) and self.last_ctx is not None and self.last_ctx.guild_id is not None

        userlog = self.app.get_plugin("Logging")
        assert userlog is not None

        log_channels = await userlog.d.actions.get_log_channel_ids_view(self.last_ctx.guild_id)

        embed = hikari.Embed(
            title="Logging Settings",
            description="Below you can see a list of logging events and channels associated with them. To change where a certain event's logs should be sent, click on the corresponding button.",
            color=const.EMBED_BLUE,
        )

        assert self.last_ctx.app_permissions is not None
        if not (self.last_ctx.app_permissions & hikari.Permissions.VIEW_AUDIT_LOG):
            embed.add_field(
                name="⚠️ Warning!",
                value=f"The bot currently has no permissions to view the audit logs! This will severely limit logging capabilities. Please consider enabling `View Audit Log` for the bot in your server's settings!",
                inline=False,
            )

        options = []

        for log_category, channel_id in log_channels.items():
            channel = self.app.cache.get_guild_channel(channel_id) if channel_id else None
            embed.add_field(
                name=f"{log_event_strings[log_category]}",
                value=channel.mention if channel else "*Not set*",
                inline=True,
            )
            options.append(miru.SelectOption(label=log_event_strings[log_category], value=log_category))

        self.select_screen(OptionsSelect(options=options, placeholder="Select a category..."), parent="Main")
        is_color = await userlog.d.actions.is_color_enabled(self.last_ctx.guild_id)
        self.add_item(BooleanButton(state=is_color, label="Color logs"))

        await self.last_ctx.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value:
            return

        if isinstance(self.value, tuple) and self.value[0] == "Color logs":
            await self.app.db.execute(
                """INSERT INTO log_config (color, guild_id) 
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO
                UPDATE SET color = $1""",
                self.value[1],
                self.last_ctx.guild_id,
            )
            await self.app.db_cache.refresh(table="log_config", guild_id=self.last_ctx.guild_id)
            return await self.settings_logging()

        log_event = self.value

        options = []
        options.append(miru.SelectOption(label="Disable", value="disable", description="Stop logging this event."))
        options += [
            miru.SelectOption(label=str(channel.name), value=str(channel.id), emoji=const.EMOJI_CHANNEL)
            for channel in self.app.cache.get_guild_channels_view_for_guild(self.last_ctx.guild_id).values()
            if isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel))
        ]

        embed = hikari.Embed(
            title="Logging Settings",
            description=f"Please select a channel where the following event should be logged: `{log_event_strings[log_event]}`",
            color=const.EMBED_BLUE,
        )

        try:
            channel = await ask_settings(
                self,
                self.last_ctx,
                options=options,
                return_type=hikari.TextableGuildChannel,
                embed_or_content=embed,
                placeholder="Select a channel...",
                ignore=["disable"],
                ephemeral=self.ephemeral,
            )
        except TypeError:
            embed = hikari.Embed(
                title="❌ Channel not found.",
                description="Unable to locate channel. Please type a channel mention or ID.",
                color=const.ERROR_COLOR,
            )
            return await self.error_screen(embed, parent="Logging")
        else:
            channel_id = channel.id if channel and channel != "disable" else None
            userlog = self.app.get_plugin("Logging")
            assert userlog is not None
            await userlog.d.actions.set_log_channel(log_event, self.last_ctx.guild_id, channel_id)

            await self.settings_logging()

    async def settings_automod(self) -> None:
        """Open and handle automoderation main menu"""

        assert isinstance(self.app, SnedBot) and self.last_ctx is not None and self.last_ctx.guild_id is not None

        automod = self.app.get_plugin("Auto-Moderation")

        assert automod is not None

        policies = await automod.d.actions.get_policies(self.last_ctx.guild_id)
        embed = hikari.Embed(
            title="Automoderation Settings",
            description="Below you can see a summary of the current automoderation settings. To see more details about a specific entry or change their settings, select it below!",
            color=const.EMBED_BLUE,
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

        self.select_screen(OptionsSelect(options=options, placeholder="Select a policy..."), parent="Main")
        await self.last_ctx.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value:
            return
        await self.settings_automod_policy(self.value)

    async def settings_automod_policy(self, policy: t.Optional[str] = None) -> None:
        """Settings for an automoderation policy"""

        assert isinstance(self.app, SnedBot) and self.last_ctx is not None and self.last_ctx.guild_id is not None

        if not policy:
            return await self.settings_automod()

        automod = self.app.get_plugin("Auto-Moderation")

        assert automod is not None

        policies: t.Dict[str, t.Any] = await automod.d.actions.get_policies(self.last_ctx.guild_id)
        policy_data = policies[policy]
        embed = hikari.Embed(
            title=f"Options for: {policy_strings[policy]['name']}",
            description=policy_strings[policy]["description"],
            color=const.EMBED_BLUE,
        )

        state = policy_data["state"]
        buttons = []

        if state == "disabled":
            embed.add_field(
                name="ℹ️ Disclaimer:",
                value="More configuration options will appear if you enable/change the state of this entry!",
                inline=False,
            )

        elif state == "escalate" and policies["escalate"]["state"] == "disabled":
            embed.add_field(
                name="⚠️ Warning:",
                value='Escalation action was not set! Please select the "Escalation" policy and set an action!',
                inline=False,
            )

        elif state in ["flag", "notice"]:
            userlog = self.app.get_plugin("Logging")
            assert userlog is not None
            channel_id = await userlog.d.actions.get_log_channel_id("flags", self.last_ctx.guild_id)
            if not channel_id:
                embed.add_field(
                    name="⚠️ Warning:",
                    value="State is set to flag or notice, but auto-mod flags are not logged! Please set a log-channel for it in `Logging` settings!",
                    inline=False,
                )

        embed.add_field(name="State:", value=state.capitalize(), inline=False)
        buttons.append(OptionButton(label="State", custom_id="state", style=hikari.ButtonStyle.SECONDARY))

        # Conditions for certain attributes to appear
        predicates = {
            "temp_dur": lambda s: s in ["timeout", "tempban"]
            or s == "escalate"
            and policies["escalate"]["state"] in ["timeout", "tempban"],
        }

        if policy_data.get("excluded_channels") is not None and policy_data.get("excluded_roles") is not None:
            """Exclusions calculations"""

            excluded_channels = [
                self.app.cache.get_guild_channel(channel_id) for channel_id in policy_data["excluded_channels"]
            ]
            excluded_roles = [self.app.cache.get_role(role_id) for role_id in policy_data["excluded_roles"]]
            excluded_channels = list(filter(None, excluded_channels))
            excluded_roles = list(filter(None, excluded_roles))

            all_channels = [
                channel
                for channel in self.app.cache.get_guild_channels_view_for_guild(self.last_ctx.guild_id).values()
                if isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel))
            ]
            included_channels = list(set(all_channels) - set(excluded_channels))  # type: ignore

            all_roles = [
                role
                for role in self.app.cache.get_roles_view_for_guild(self.last_ctx.guild_id).values()
                if role.id != self.last_ctx.guild_id
            ]
            included_roles = list(set(all_roles) - set(excluded_roles))

        if state != "disabled":
            for key in policy_data:
                if key == "state":
                    continue

                if predicate := predicates.get(key):
                    if not predicate(state):
                        continue

                if key in ["excluded_channels", "excluded_roles"]:
                    continue

                value = (
                    policy_data[key]
                    if not isinstance(policy_data[key], dict)
                    else "\n".join(
                        [
                            f"{polkey.replace('_', ' ').title()}: `{str(value)}`"
                            for polkey, value in policy_data[key].items()
                        ]
                    )
                )
                value = value if not isinstance(policy_data[key], list) else ", ".join(policy_data[key])
                if len(str(value)) > 512:  # Account for long field values
                    value = str(value)[: 512 - 3] + "..."

                embed.add_field(
                    name=policy_fields[key]["name"],
                    value=policy_fields[key]["value"].format(value=value),
                    inline=False,
                )
                buttons.append(
                    OptionButton(label=policy_fields[key]["label"], custom_id=key, style=hikari.ButtonStyle.SECONDARY)
                )

            if policy_data.get("excluded_channels") is not None and policy_data.get("excluded_roles") is not None:
                display_channels = ", ".join([channel.mention for channel in excluded_channels])  # type: ignore it's not unbound, trust me c:
                display_roles = ", ".join([role.mention for role in excluded_roles])  # type: ignore

                if len(display_channels) > 512:
                    display_channels = display_channels[: 512 - 3] + "..."

                if len(display_roles) > 512:
                    display_roles = display_roles[: 512 - 3] + "..."

                embed.add_field(
                    name=policy_fields["excluded_channels"]["name"],
                    value=display_channels if excluded_channels else "*None set*",  # type: ignore
                    inline=False,
                )

                embed.add_field(
                    name=policy_fields["excluded_roles"]["name"],
                    value=display_roles if excluded_roles else "*None set*",  # type: ignore
                    inline=False,
                )

                buttons.append(
                    OptionButton(
                        label="Channel",
                        emoji="➕",
                        custom_id="add_channel",
                        style=hikari.ButtonStyle.SUCCESS,
                        row=4,
                        disabled=not included_channels,  # type: ignore
                    )
                )
                buttons.append(
                    OptionButton(
                        label="Role",
                        emoji="➕",
                        custom_id="add_role",
                        style=hikari.ButtonStyle.SUCCESS,
                        row=4,
                        disabled=not included_roles,  # type: ignore
                    )
                )
                buttons.append(
                    OptionButton(
                        label="Channel",
                        emoji="➖",
                        custom_id="del_channel",
                        style=hikari.ButtonStyle.DANGER,
                        row=4,
                        disabled=not excluded_channels,  # type: ignore
                    )
                )
                buttons.append(
                    OptionButton(
                        label="Role",
                        emoji="➖",
                        custom_id="del_role",
                        style=hikari.ButtonStyle.DANGER,
                        row=4,
                        disabled=not excluded_roles,  # type: ignore
                    )
                )

        if settings_help["policies"].get(policy) is not None:
            buttons.append(OptionButton(label="Help", custom_id="show_help", emoji="❓"))

        self.add_buttons(buttons, parent="Auto-Moderation")
        await self.last_ctx.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value:
            return

        sql = """
        INSERT INTO mod_config (automod_policies, guild_id)
        VALUES ($1, $2) 
        ON CONFLICT (guild_id) DO
        UPDATE SET automod_policies = $1"""

        # The option that is to be changed
        assert self.last_item is not None
        opt = self.last_item.custom_id

        # Question types
        actions = {
            "show_help": ["show_help"],
            "boolean": ["delete"],
            "text_input": ["temp_dur", "words_list", "words_list_wildcard", "count", "persp_bounds"],
            "ask": ["add_channel", "add_role", "del_channel", "del_role"],
            "select": ["state"],
        }

        # Values that should be converted from & to lists
        # This is only valid for text_input action type
        list_inputs = ["words_list", "words_list_wildcard"]

        # Expected return type for a question
        expected_types = {
            "temp_dur": int,
            "words_list": list,
            "words_list_wildcard": list,
            "count": int,
            "excluded_channels": str,
            "excluded_roles": str,
        }

        action = [key for key in actions if opt in actions[key]][0]

        if opt == "state":  # State changing is a special case, ignore action

            options = [
                miru.SelectOption(
                    value=state,
                    label=policy_states[state]["name"],
                    description=policy_states[state]["description"],
                    emoji=policy_states[state]["emoji"],
                )
                for state in policy_states.keys()
                if policy not in policy_states[state]["excludes"]
            ]
            self.select_screen(
                OptionsSelect(options=options, placeholder="Select the state of this policy..."),
                parent="Auto-Moderation",
            )
            embed = hikari.Embed(
                title="Select state...", description="Select a new state for this policy...", color=const.EMBED_BLUE
            )
            await self.last_ctx.edit_response(embed=embed, components=self, flags=self.flags)
            await self.wait_for_input()

            if not self.value:
                return

            policies[policy]["state"] = self.value

        elif action == "boolean":
            policies[policy][opt] = not policies[policy][opt]

        elif opt == "persp_bounds":
            modal = PerspectiveBoundsModal(self, policy_data["persp_bounds"], title="Changing Perspective Bounds...")
            assert isinstance(self.last_ctx, miru.ViewContext)
            await self.last_ctx.respond_with_modal(modal)
            await self.wait_for_input()

            if not self.value:
                return

            try:
                assert isinstance(self.value, dict)
                for key, value in self.value.items():
                    self.value[key] = float(value.replace(",", "."))
                    if not (0.1 <= float(self.value[key]) <= 1.0):
                        raise ValueError
            except (ValueError, TypeError):
                embed = hikari.Embed(
                    title="❌ Invalid Type",
                    description=f"One or more values were not floating-point numbers, or were not between `0.1`-`1.0`!",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Auto-Moderation Policies", policy=policy)

            policies["perspective"]["persp_bounds"] = self.value

        elif action == "text_input":
            assert opt is not None

            modal = OptionsModal(self, f"Changing {policy_fields[opt]['label']}...")
            # Deepcopy because we store instances for convenience
            text_input = copy.deepcopy(policy_text_inputs[opt])
            # Prefill only bad words
            if opt in list_inputs:
                text_input.value = ", ".join(policies[policy][opt])
            modal.add_item(text_input)

            assert isinstance(self.last_ctx, miru.ViewContext)
            await self.last_ctx.respond_with_modal(modal)
            await self.wait_for_input()

            if not self.value:
                return

            assert isinstance(self.value, dict)
            value = list(self.value.values())[0]

            if opt in list_inputs:
                value = [list_item.strip().lower() for list_item in value.split(",")]
                value = list(filter(None, value))  # Remove empty values

            try:
                value = expected_types[opt](value)
                if isinstance(value, int):
                    value = abs(value)
                    if value == 0:
                        raise ValueError

            except (TypeError, ValueError):
                embed = hikari.Embed(
                    title="❌ Invalid Type",
                    description=f"Expected a **number** (that is not zero) for option `{policy_fields[opt]['label']}`.",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Auto-Moderation Policies", policy=policy)

            policies[policy][opt] = value

        elif action == "ask":

            if opt in ["add_channel", "add_role", "del_channel", "del_role"]:
                match opt:
                    case "add_channel":
                        options = [
                            miru.SelectOption(label=channel.name, value=channel.id, emoji=const.EMOJI_CHANNEL)
                            for channel in included_channels  # type: ignore
                        ]
                        embed = hikari.Embed(
                            title="Auto-Moderation Settings",
                            description="Choose a channel to add to excluded channels!",
                            color=const.EMBED_BLUE,
                        )
                        return_type = hikari.TextableGuildChannel
                    case "del_channel":
                        options = [
                            miru.SelectOption(label=channel.name, value=channel.id, emoji=const.EMOJI_CHANNEL)
                            for channel in excluded_channels  # type: ignore
                        ]
                        embed = hikari.Embed(
                            title="Auto-Moderation Settings",
                            description="Choose a channel to remove from excluded channels!",
                            color=const.EMBED_BLUE,
                        )
                        return_type = hikari.TextableGuildChannel
                    case "add_role":
                        options = [
                            miru.SelectOption(label=role.name, value=role.id, emoji=const.EMOJI_MENTION)
                            for role in included_roles  # type: ignore
                        ]
                        embed = hikari.Embed(
                            title="Auto-Moderation Settings",
                            description="Choose a role to add to excluded roles!",
                            color=const.EMBED_BLUE,
                        )
                        return_type = hikari.Role
                    case "del_role":
                        options = [
                            miru.SelectOption(label=role.name, value=role.id, emoji=const.EMOJI_MENTION)
                            for role in excluded_roles  # type: ignore
                        ]
                        embed = hikari.Embed(
                            title="Auto-Moderation Settings",
                            description="Choose a role to remove from excluded roles!",
                            color=const.EMBED_BLUE,
                        )
                        return_type = hikari.Role

                try:
                    value = await ask_settings(
                        self,
                        self.last_ctx,
                        options=options,  # type: ignore
                        embed_or_content=embed,
                        return_type=return_type,  # type: ignore
                        placeholder="Select a value...",
                        ephemeral=self.ephemeral,
                    )
                    if not value:
                        return await self.settings_automod_policy(policy)
                    if opt.startswith("add_"):
                        if value.id not in policies[policy][f"excluded_{opt.split('_')[1]}s"]:
                            policies[policy][f"excluded_{opt.split('_')[1]}s"].append(value.id)
                    elif opt.startswith("del_"):
                        if value.id in policies[policy][f"excluded_{opt.split('_')[1]}s"]:
                            policies[policy][f"excluded_{opt.split('_')[1]}s"].remove(value.id)
                        else:
                            raise ValueError("Value not excluded.")

                except (TypeError, ValueError):
                    embed = hikari.Embed(
                        title="❌ Invalid Type",
                        description=f"Cannot find the channel/role specified or it is not in the excluded roles/channels.",
                        color=const.ERROR_COLOR,
                    )
                    return await self.error_screen(embed, parent="Auto-Moderation Policies", policy=policy)

        elif action == "show_help":
            embed = settings_help["policies"][policy]
            return await self.error_screen(embed, parent="Auto-Moderation Policies", policy=policy)

        await self.app.db.execute(sql, json.dumps(policies), self.last_ctx.guild_id)
        await self.app.db_cache.refresh(table="mod_config", guild_id=self.last_ctx.guild_id)
        return await self.settings_automod_policy(policy)


T = t.TypeVar("T")


async def ask_settings(
    view: SettingsView,
    ctx: miru.Context,
    *,
    options: t.List[miru.SelectOption],
    return_type: T,
    embed_or_content: t.Union[str, hikari.Embed],
    placeholder: t.Optional[str] = None,
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
            f"return_type must be of types: {' '.join(list(CONVERTER_TYPE_MAPPING.keys()))}, not {return_type}"  # type: ignore
        )

    # Get appropiate converter for return type
    converter: lightbulb.BaseConverter = CONVERTER_TYPE_MAPPING[return_type](view.lctx)  # type: ignore
    flags = hikari.MessageFlag.EPHEMERAL if ephemeral else hikari.MessageFlag.NONE

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
        await ctx.edit_response(content=content, embeds=embeds, components=view, flags=flags)
        await view.wait_for_input()

        if view.value:
            if ignore and view.value.casefold() in ignore:
                return view.value.casefold()
            return await converter.convert(view.value)

        await view.quit_settings()

    else:
        await ctx.defer(flags=flags)
        if embeds:
            embeds[0].description = f"{embeds[0].description}\n\nPlease type your response below!"
        elif content:
            content = f"{content}\n\nPlease type your response below!"

        await ctx.edit_response(content=content, embeds=embeds, components=[], flags=flags)

        predicate = lambda e: e.author.id == ctx.user.id and e.channel_id == ctx.channel_id

        assert isinstance(ctx.app, SnedBot) and ctx.guild_id is not None

        try:
            event = await ctx.app.wait_for(hikari.GuildMessageCreateEvent, timeout=300.0, predicate=predicate)
        except asyncio.TimeoutError:
            return await view.quit_settings()

        me = ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id)
        channel = event.get_channel()
        assert me is not None
        if channel:  # Make reasonable attempt at perms
            perms = lightbulb.utils.permissions_in(channel, me)

            if helpers.includes_permissions(perms, hikari.Permissions.MANAGE_MESSAGES):
                await helpers.maybe_delete(event.message)

        if event.content:
            if ignore and event.content.casefold() in ignore:
                return event.content.casefold()
            return await converter.convert(event.content)


@settings.command
@lightbulb.app_command_permissions(hikari.Permissions.MANAGE_GUILD, dm_enabled=False)
@lightbulb.set_max_concurrency(1, lightbulb.GuildBucket)
@lightbulb.add_checks(
    bot_has_permissions(hikari.Permissions.SEND_MESSAGES, hikari.Permissions.VIEW_CHANNEL),
)
@lightbulb.command("settings", "Adjust different settings of the bot via an interactive menu.")
@lightbulb.implements(lightbulb.SlashCommand)
async def settings_cmd(ctx: SnedSlashContext) -> None:
    assert ctx.guild_id is not None
    ephemeral = bool((await ctx.app.mod.get_settings(ctx.guild_id)).flags & ModerationFlags.IS_EPHEMERAL)
    view = SettingsView(ctx, timeout=300, ephemeral=ephemeral)
    await view.start_settings()


def load(bot: SnedBot) -> None:
    bot.add_plugin(settings)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(settings)


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
