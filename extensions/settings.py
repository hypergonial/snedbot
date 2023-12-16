from __future__ import annotations

import asyncio
import copy
import datetime
import json
import typing as t
from contextlib import suppress

import hikari
import lightbulb
import miru

import models
from etc import const
from etc.settings_static import *
from extensions.userlog import LogEvent
from models.bot import SnedBot
from models.checks import bot_has_permissions
from models.mod_actions import ModerationFlags
from models.plugin import SnedPlugin
from models.settings import *
from models.starboard import StarboardSettings
from utils import helpers

if t.TYPE_CHECKING:
    from miru.abc import ViewItem

    from models.context import SnedSlashContext

settings = SnedPlugin("Settings")


class SettingsView(models.AuthorOnlyView):
    """God objects go brr >_<."""

    def __init__(
        self,
        lctx: lightbulb.Context,
        *,
        timeout: float | None = 300,
        ephemeral: bool = False,
        autodefer: bool = False,
    ) -> None:
        super().__init__(lctx, timeout=timeout, autodefer=autodefer)

        self.last_item: ViewItem | None = None
        """Last component that was interacted with."""

        self.value: SettingValue = SettingValue()
        """Last value received as input wrapped in a monadic type for type safety."""

        self.ephemeral: bool = ephemeral
        """If True, provides the menu ephemerally."""

        self.flags = hikari.MessageFlag.EPHEMERAL if self.ephemeral else hikari.MessageFlag.NONE
        """Flags to pass with every message edit."""

        self._done_event: asyncio.Event = asyncio.Event()
        """Event that is set and cleared when a DoneButton or BackButton is pressed, or the view stops."""

        self.menu_actions: dict[str, t.Callable[..., t.Awaitable[None]]] = {
            "Main": self.settings_main,
            "Reports": self.settings_report,
            "Moderation": self.settings_mod,
            "Auto-Moderation": self.settings_automod,
            "Auto-Moderation Policies": self.settings_automod_policy,
            "Logging": self.settings_logging,
            "Starboard": self.settings_starboard,
            "Quit": self.quit_settings,
        }
        """Mapping of custom_id/label, menu action"""

    async def wait_until_done(self) -> None:
        """Wait until a DoneButton is pressed.
        Check `self.value.is_done` to ensure this did not unblock due to the view stopping or some other reason.
        """
        await self._done_event.wait()

    # Transitions
    def add_buttons(self, buttons: t.Sequence[miru.Button], parent: str | None = None, **kwargs) -> None:
        """Add a new set of buttons, clearing previous components."""
        self.clear_items()

        if parent:
            self.add_item(BackButton(parent, **kwargs))
        else:
            self.add_item(QuitButton())

        for button in buttons:
            self.add_item(button)

    def select_screen(
        self, select: miru.SelectBase, parent: str | None = None, with_done: bool = False, **kwargs
    ) -> None:
        """Set view to a new select screen, clearing previous components."""
        self.clear_items()

        self.add_item(select)

        if parent:
            self.add_item(BackButton(parent, **kwargs))
        else:
            self.add_item(QuitButton())

        if with_done and parent:
            self.add_item(DoneButton(parent, **kwargs))

    async def error_screen(self, embed: hikari.Embed, parent: str, **kwargs) -> None:
        """Show an error screen with only a back button, and wait for input on it."""
        assert self.last_context
        self.clear_items()
        self.add_item(BackButton(parent=parent, **kwargs))
        await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

    async def on_timeout(self) -> None:
        """Stop waiting for input events after the view times out."""
        self.value = SettingValue()
        self._done_event.set()

        if not self.last_context:
            return

        for item in self.children:
            item.disabled = True

        with suppress(hikari.NotFoundError):
            await self.last_context.edit_response(components=self, flags=self.flags)

    async def quit_settings(self) -> None:
        """Exit settings menu."""
        assert self.last_context
        for item in self.children:
            item.disabled = True

        with suppress(hikari.NotFoundError):
            await self.last_context.edit_response(components=self, flags=self.flags)

        self.value = SettingValue()
        self._done_event.set()
        self.stop()

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
            assert self.last_context is not None
            await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)

        await self.wait_for_input()
        if self.value.text is hikari.UNDEFINED:
            return

        await self.menu_actions[self.value.text]()

    async def settings_report(self) -> None:
        """The reports menu."""
        assert isinstance(self.app, SnedBot) and self.last_context and self.last_context.guild_id

        records = await self.app.db_cache.get(table="reports", guild_id=self.last_context.guild_id, limit=1)

        if not records:
            records = [
                {
                    "guild_id": self.last_context.guild_id,
                    "is_enabled": False,
                    "channel_id": None,
                    "pinged_role_ids": None,
                }
            ]

        pinged_roles = (
            [self.app.cache.get_role(role_id) for role_id in records[0]["pinged_role_ids"]]
            if records[0]["pinged_role_ids"]
            else []
        )
        """ all_roles = [
            role
            for role in list(self.app.cache.get_roles_view_for_guild(self.last_context.guild_id).values())
            if role.id != self.last_context.guild_id
        ]
        unadded_roles = list(set(all_roles) - set(pinged_roles)) """

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
            BooleanButton(state=records[0]["is_enabled"] if channel else False, label="Enabled", disabled=not channel),
            OptionButton(label="Set Channel", emoji=const.EMOJI_CHANNEL, style=hikari.ButtonStyle.SECONDARY),
            OptionButton(label="Change Roles", emoji=const.EMOJI_MENTION, style=hikari.ButtonStyle.SECONDARY),
        ]
        self.add_buttons(buttons, parent="Main")
        await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value:
            return

        if self.value.boolean is not hikari.UNDEFINED:
            await self.app.db.execute(
                """INSERT INTO reports (is_enabled, guild_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO
                UPDATE SET is_enabled = $1""",
                self.value.boolean,
                self.last_context.guild_id,
            )
            await self.app.db_cache.refresh(table="reports", guild_id=self.last_context.guild_id)

        elif self.value.text == "Set Channel":
            embed = hikari.Embed(
                title="Reports Settings",
                description="Please select a channel where reports will be sent.",
                color=const.EMBED_BLUE,
            )

            select = OptionsChannelSelect(
                channel_types=(hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS),
                placeholder="Select a channel...",
            )
            self.select_screen(select, parent="Reports")
            await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
            await self.wait_for_input()

            if not self.value.channels:
                return

            await self.app.db.execute(
                """INSERT INTO reports (channel_id, guild_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO
                UPDATE SET channel_id = $1""",
                self.value.channels[0].id,
                self.last_context.guild_id,
            )
            await self.app.db_cache.refresh(table="reports", guild_id=self.last_context.guild_id)

        elif self.value.text == "Change Roles":
            embed = hikari.Embed(
                title="Reports Settings",
                description="Select the roles that will be mentioned when a new report is made.\nTo remove all roles, hit 'Done' without selecting anything.",
                color=const.EMBED_BLUE,
            )

            select = OptionsRoleSelect(placeholder="Select roles...", min_values=0, max_values=10, with_done=True)
            self.select_screen(select, parent="Reports", with_done=True)
            await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
            await self.wait_until_done()

            if not self.value.is_done:
                return

            await self.app.db.execute(
                """INSERT INTO reports (pinged_role_ids, guild_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO
                UPDATE SET pinged_role_ids = $1""",
                [role.id for role in self.value.roles] if self.value.roles else None,
                self.last_context.guild_id,
            )
            await self.app.db_cache.refresh(table="reports", guild_id=self.last_context.guild_id)

        await self.settings_report()

    async def settings_mod(self) -> None:
        """Show and handle Moderation menu."""
        assert (
            isinstance(self.app, SnedBot) and self.last_context is not None and self.last_context.guild_id is not None
        )

        mod_settings = await self.app.mod.get_settings(self.last_context.guild_id)

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
        await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value:
            return

        assert self.last_item and self.last_item.custom_id
        flag = ModerationFlags(int(self.last_item.custom_id))

        await self.app.db.execute(
            """
            INSERT INTO mod_config (guild_id, flags)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO
            UPDATE SET flags = $2""",
            self.last_context.guild_id,
            (mod_settings.flags & ~flag).value if flag & mod_settings.flags else (mod_settings.flags | flag).value,
        )
        await self.app.db_cache.refresh(table="mod_config", guild_id=self.last_context.guild_id)

        await self.settings_mod()

    async def settings_starboard(self) -> None:
        assert (
            isinstance(self.app, SnedBot) and self.last_context is not None and self.last_context.guild_id is not None
        )

        settings = await StarboardSettings.fetch(self.last_context.guild_id)

        starboard_channel = self.app.cache.get_guild_channel(settings.channel_id) if settings.channel_id else None
        is_enabled = settings.is_enabled if settings.channel_id else False

        excluded_channels = (
            [self.app.cache.get_guild_channel(channel_id) for channel_id in settings.excluded_channels]
            if settings.excluded_channels
            else []
        )

        embed = hikari.Embed(
            title="Starboard Settings",
            description="Below you can see the current settings for this server's starboard! If enabled, users can star messages by reacting with ⭐, and if the number of reactions reaches the specified limit, the message will be sent into the specified starboard channel.",
            color=const.EMBED_BLUE,
        )
        buttons = [
            BooleanButton(state=is_enabled, label="Enabled", disabled=not starboard_channel),
            OptionButton(style=hikari.ButtonStyle.SECONDARY, label="Set Channel", emoji=const.EMOJI_CHANNEL),
            OptionButton(style=hikari.ButtonStyle.SECONDARY, label="Limit", emoji="⭐"),
            OptionButton(style=hikari.ButtonStyle.SECONDARY, label="Exclusions"),
        ]
        embed.add_field(
            "Starboard Channel", starboard_channel.mention if starboard_channel else "*Not set*", inline=True
        )
        embed.add_field("Star Limit", str(settings.star_limit), inline=True)
        embed.add_field(
            "Excluded Channels",
            " ".join([channel.mention for channel in excluded_channels if channel])[:512]
            if excluded_channels
            else "*Not set*",
            inline=True,
        )
        self.add_buttons(buttons, parent="Main")
        await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value:
            return

        if self.value.boolean is not hikari.UNDEFINED and self.value.text == "Enabled":
            settings.is_enabled = self.value.boolean

        elif self.value.text == "Limit":
            modal = OptionsModal(self, title="Changing star limit...").add_item(
                miru.TextInput(
                    label="Star Limit",
                    required=True,
                    max_length=3,
                    value=str(settings.star_limit),
                    placeholder="Enter a positive integer to be set as the minimum required amount of stars...",
                )
            )
            assert isinstance(self.last_context, miru.ViewContext)
            await self.last_context.respond_with_modal(modal)
            await self.wait_for_input()

            if not self.value.modal_values:
                return

            if modal.last_context is None:
                return

            self._last_context = modal.last_context  # type: ignore

            limit_str: str = next(iter(self.value.modal_values.values()))

            try:
                limit = abs(int(limit_str))
                if limit == 0:
                    raise ValueError

            except (TypeError, ValueError):
                embed = hikari.Embed(
                    title="❌ Invalid Type",
                    description="Expected a non-zero **number**.",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Starboard")

            settings.star_limit = limit

        elif self.value.text == "Set Channel":
            embed = hikari.Embed(
                title="Starboard Settings",
                description="Please select a channel where starred messages will be sent.",
                color=const.EMBED_BLUE,
            )

            select = OptionsChannelSelect(
                channel_types=(hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS),
                placeholder="Select a channel...",
            )
            self.select_screen(select, parent="Starboard")
            await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
            await self.wait_for_input()

            if not self.value.channels:
                return

            settings.channel_id = self.value.channels[0].id

        elif self.value.text == "Exclusions":
            embed = hikari.Embed(
                title="Starboard Settings",
                description="Select channels to be excluded. Users will not be able to star messages from these channels.\n\nTo remove all exclusions, click `Done` without a selection.",
                color=const.EMBED_BLUE,
            )

            select = OptionsChannelSelect(
                channel_types=(hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS),
                placeholder="Select channels...",
                min_values=0,
                max_values=25,
                with_done=True,
            )
            self.select_screen(select, parent="Starboard", with_done=True)
            await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
            await self.wait_until_done()

            if not self.value.is_done:
                return

            settings.excluded_channels = (
                [channel.id for channel in self.value.channels] if self.value.channels else None
            )

        await settings.update()
        await self.settings_starboard()

    async def settings_logging(self) -> None:
        """Show and handle Logging menu."""
        assert (
            isinstance(self.app, SnedBot) and self.last_context is not None and self.last_context.guild_id is not None
        )

        userlog = self.app.get_plugin("Logging")
        assert userlog is not None

        log_channels = await userlog.d.actions.get_log_channel_ids_view(self.last_context.guild_id)

        embed = hikari.Embed(
            title="Logging Settings",
            description="Below you can see a list of logging events and channels associated with them. To change where a certain event's logs should be sent, select it below.",
            color=const.EMBED_BLUE,
        )

        assert self.last_context.app_permissions is not None
        if not (self.last_context.app_permissions & hikari.Permissions.VIEW_AUDIT_LOG):
            embed.add_field(
                name="⚠️ Warning!",
                value="The bot currently has no permissions to view the audit logs! This will severely limit logging capabilities. Please consider enabling `View Audit Log` for the bot in your server's settings!",
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

        self.select_screen(OptionsTextSelect(options=options, placeholder="Select a category..."), parent="Main")
        is_color = await userlog.d.actions.is_color_enabled(self.last_context.guild_id)
        self.add_item(BooleanButton(state=is_color, label="Color logs"))

        await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value.text:
            return

        if self.value.boolean is not hikari.UNDEFINED and self.value.text == "Color logs":
            await self.app.db.execute(
                """INSERT INTO log_config (color, guild_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO
                UPDATE SET color = $1""",
                self.value.boolean,
                self.last_context.guild_id,
            )
            await self.app.db_cache.refresh(table="log_config", guild_id=self.last_context.guild_id)
            return await self.settings_logging()

        log_event = self.value.text

        options = []
        options.append(miru.SelectOption(label="Disable", value="disable", description="Stop logging this event."))
        options += [
            miru.SelectOption(label=str(channel.name), value=str(channel.id), emoji=const.EMOJI_CHANNEL)
            for channel in self.app.cache.get_guild_channels_view_for_guild(self.last_context.guild_id).values()
            if isinstance(channel, (hikari.GuildTextChannel, hikari.GuildNewsChannel))
        ]

        embed = hikari.Embed(
            title="Logging Settings",
            description=f"Please select a channel where the following event should be logged: `{log_event_strings[log_event]}`\n\nTo disable logging for this event, hit `Done` without selecting anything.",
            color=const.EMBED_BLUE,
        )

        select = OptionsChannelSelect(
            channel_types=(hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS),
            placeholder="Select a channel...",
            with_done=True,
            min_values=0,
        )
        self.select_screen(select, parent="Logging", with_done=True)
        await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)

        await self.wait_until_done()

        if not self.value.is_done:
            return

        channel = self.value.channels[0] if self.value.channels else None
        userlog = self.app.get_plugin("Logging")
        assert userlog is not None
        await userlog.d.actions.set_log_channel(
            LogEvent(log_event), self.last_context.guild_id, channel.id if channel else None
        )

        await self.settings_logging()

    async def settings_automod(self) -> None:
        """Open and handle automoderation main menu."""
        assert (
            isinstance(self.app, SnedBot) and self.last_context is not None and self.last_context.guild_id is not None
        )

        automod = self.app.get_plugin("Auto-Moderation")

        assert automod is not None

        policies = await automod.d.actions.get_policies(self.last_context.guild_id)
        embed = hikari.Embed(
            title="Automoderation Settings",
            description="Below you can see a summary of the current automoderation settings. To see more details about a specific entry or change their settings, select it below!",
            color=const.EMBED_BLUE,
        )

        options = []
        for key in policies:
            embed.add_field(
                name=policy_strings[key]["name"],
                value=policies[key]["state"].capitalize(),
                inline=True,
            )
            # TODO: Add emojies maybe?
            options.append(miru.SelectOption(label=policy_strings[key]["name"], value=key))

        self.select_screen(OptionsTextSelect(options=options, placeholder="Select a policy..."), parent="Main")
        await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value.text:
            return
        await self.settings_automod_policy(self.value.text)

    async def settings_automod_policy(self, policy: str | None = None) -> None:
        """Settings for an automoderation policy."""
        assert (
            isinstance(self.app, SnedBot) and self.last_context is not None and self.last_context.guild_id is not None
        )

        if not policy:
            return await self.settings_automod()

        automod = self.app.get_plugin("Auto-Moderation")

        assert automod is not None

        policies: dict[str, t.Any] = await automod.d.actions.get_policies(self.last_context.guild_id)
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
            channel_id = await userlog.d.actions.get_log_channel_id(LogEvent.FLAGS, self.last_context.guild_id)
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

        if state != "disabled":
            for key in policy_data:
                if key == "state":
                    continue

                if (predicate := predicates.get(key)) and not predicate(state):
                    continue

                if key in ["excluded_channels", "excluded_roles"]:
                    continue

                value = (
                    policy_data[key]
                    if not isinstance(policy_data[key], dict)
                    else "\n".join(
                        [f"{polkey.replace('_', ' ').title()}: `{value}`" for polkey, value in policy_data[key].items()]
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
                display_channels = ", ".join([channel.mention for channel in excluded_channels])  # type: ignore
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
                        label="Excluded Channels",
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id="exclude_channels",
                        row=4,
                    )
                )
                buttons.append(
                    OptionButton(
                        label="Excluded Roles",
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id="exclude_roles",
                        row=4,
                    )
                )

        if settings_help["policies"].get(policy) is not None:
            buttons.append(OptionButton(label="Help", custom_id="show_help", emoji="❓"))

        self.add_buttons(buttons, parent="Auto-Moderation")
        await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
        await self.wait_for_input()

        if not self.value.text:
            return

        sql = """
        INSERT INTO mod_config (automod_policies, guild_id)
        VALUES ($1, $2) 
        ON CONFLICT (guild_id) DO
        UPDATE SET automod_policies = $1"""

        # The option that is to be changed
        assert self.last_item is not None
        opt: str = self.last_item.custom_id

        # Question types
        actions = {
            "show_help": ["show_help"],
            "boolean": ["delete"],
            "text_input": ["temp_dur", "words_list", "words_list_wildcard", "count", "persp_bounds"],
            "select": ["state", "exclude_channels", "exclude_roles"],
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

        action = next(key for key in actions if opt in actions[key])

        if opt == "state":  # State changing is a special case, ignore action
            options = [
                miru.SelectOption(
                    value=state,
                    label=policy_states[state]["name"],
                    description=policy_states[state]["description"],
                    emoji=policy_states[state]["emoji"],
                )
                for state in policy_states
                if policy not in policy_states[state]["excludes"]
            ]
            self.select_screen(
                OptionsTextSelect(options=options, placeholder="Select the state of this policy..."),
                parent="Auto-Moderation",
            )
            embed = hikari.Embed(
                title="Select state...", description="Select a new state for this policy...", color=const.EMBED_BLUE
            )
            await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
            await self.wait_for_input()

            if not self.value.text:
                return

            policies[policy]["state"] = self.value.text

        elif action == "boolean":
            policies[policy][opt] = not policies[policy][opt]

        elif opt == "persp_bounds":
            modal = PerspectiveBoundsModal(self, policy_data["persp_bounds"], title="Changing Perspective Bounds...")
            assert isinstance(self.last_context, miru.ViewContext)
            await self.last_context.respond_with_modal(modal)

            # Guard against button interactions failing if the modal is cancelled by the user
            self.add_buttons([], parent="Auto-Moderation Policies", policy=policy)
            await self.last_context.edit_response(
                embed=hikari.Embed(title="Awaiting input...", color=const.EMBED_BLUE), components=self, flags=self.flags
            )

            await self.wait_for_input()

            if not self.value.raw_perspective_bounds:
                return

            try:
                perspective_bounds = {}
                for key, value in self.value.raw_perspective_bounds.items():
                    value = float(value.replace(",", "."))
                    if not (0.1 <= value <= 1.0):
                        raise ValueError
                    perspective_bounds[key] = value
            except (ValueError, TypeError):
                embed = hikari.Embed(
                    title="❌ Invalid Type",
                    description="One or more values were not floating-point numbers, or were not between `0.1`-`1.0`!",
                    color=const.ERROR_COLOR,
                )
                return await self.error_screen(embed, parent="Auto-Moderation Policies", policy=policy)

            policies["perspective"]["persp_bounds"] = perspective_bounds

        elif action == "text_input":
            assert opt is not None

            modal = OptionsModal(self, f"Changing {policy_fields[opt]['label']}...")
            # Deepcopy because we store instances for convenience
            text_input = copy.deepcopy(policy_text_inputs[opt])
            # Prefill only bad words
            if opt in list_inputs:
                text_input.value = ", ".join(policies[policy][opt])
            modal.add_item(text_input)

            assert isinstance(self.last_context, miru.ViewContext)
            await self.last_context.respond_with_modal(modal)

            self.add_buttons([], parent="Auto-Moderation Policies", policy=policy)
            await self.last_context.edit_response(
                embed=hikari.Embed(title="Awaiting input...", color=const.EMBED_BLUE), components=self, flags=self.flags
            )

            await self.wait_for_input()

            if not self.value.modal_values:
                return

            value = next(iter(self.value.modal_values.values()))

            if opt in list_inputs:
                # Divide up and filter empty values
                value = list(filter(None, (list_item.strip().lower() for list_item in value.split(","))))

                if len(value) == 1 and value[0].casefold() == "sned":
                    embed = hikari.Embed(
                        title="I have a surprise for you!",
                        description=f"Deploying surpise in {helpers.format_dt(helpers.utcnow() + datetime.timedelta(seconds=3), 'R')}",
                        color=const.EMBED_GREEN,
                    )
                    await self.last_context.edit_response(embed=embed, components=[], flags=self.flags)
                    await asyncio.sleep(2)
                    self.add_buttons(
                        [miru.Button(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", label="Surprise!")],
                        parent="Auto-Moderation Policies",
                        policy=policy,
                    )
                    embed.description = None
                    await self.last_context.edit_response(embed=embed, components=self, flags=self.flags)
                    return

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

        elif action == "select":
            if opt == "exclude_channels":
                select = OptionsChannelSelect(
                    channel_types=(hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS),
                    placeholder="Select channels...",
                    with_done=True,
                    min_values=0,
                    max_values=25,
                )
                self.select_screen(select, parent="Auto-Moderation Policies", with_done=True, policy=policy)
                await self.last_context.edit_response(
                    embed=hikari.Embed(
                        title="Select channels to exclude...",
                        description="Select channels to exclude from this policy...\n\nTo disable channel exclusions, hit `Done` without selecting any channels.",
                    ),
                    components=self,
                    flags=self.flags,
                )

                await self.wait_until_done()

                if not self.value.is_done:
                    return

                policies[policy]["excluded_channels"] = (
                    [channel.id for channel in self.value.channels] if self.value.channels else []
                )

            elif opt == "exclude_roles":
                select = OptionsRoleSelect(placeholder="Select roles...", with_done=True, min_values=0, max_values=25)
                self.select_screen(select, parent="Auto-Moderation Policies", with_done=True, policy=policy)
                await self.last_context.edit_response(
                    embed=hikari.Embed(
                        title="Select roles to exclude...",
                        description="Select roles to exclude from this policy...\n\nTo disable role exclusions, hit `Done` without selecting any roles.",
                    ),
                    components=self,
                    flags=self.flags,
                )

                await self.wait_until_done()

                if not self.value.is_done:
                    return

                policies[policy]["excluded_roles"] = [role.id for role in self.value.roles] if self.value.roles else []

        elif action == "show_help":
            embed = settings_help["policies"][policy]
            return await self.error_screen(embed, parent="Auto-Moderation Policies", policy=policy)

        await self.app.db.execute(sql, json.dumps(policies), self.last_context.guild_id)
        await self.app.db_cache.refresh(table="mod_config", guild_id=self.last_context.guild_id)
        return await self.settings_automod_policy(policy)


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
