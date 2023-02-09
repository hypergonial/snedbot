from __future__ import annotations

import typing as t

import attr
import hikari
import miru
from miru.abc import ModalItem, ViewItem

if t.TYPE_CHECKING:
    from extensions.settings import SettingsView


@attr.define()
class SettingValue:
    """Monadic return value for a setting."""

    is_done: bool = attr.field(default=False)
    """Signals that the values contained in this object are finalized in case of a 'with_done' layout."""
    text: hikari.UndefinedOr[str] = attr.field(default=hikari.UNDEFINED)
    boolean: hikari.UndefinedOr[bool] = attr.field(default=hikari.UNDEFINED)
    users: hikari.UndefinedOr[t.Sequence[hikari.User]] = attr.field(default=hikari.UNDEFINED)
    roles: hikari.UndefinedNoneOr[t.Sequence[hikari.Role]] = attr.field(default=hikari.UNDEFINED)
    channels: hikari.UndefinedNoneOr[t.Sequence[hikari.InteractionChannel]] = attr.field(default=hikari.UNDEFINED)
    modal_values: hikari.UndefinedOr[t.Mapping[ModalItem, str]] = attr.field(default=hikari.UNDEFINED)
    raw_perspective_bounds: hikari.UndefinedOr[t.Mapping[str, str]] = attr.field(default=hikari.UNDEFINED)

    def __bool__(self) -> bool:  # To make it easier to check if a value was set.
        return bool(
            self.is_done
            or self.text is not hikari.UNDEFINED
            or self.boolean is not hikari.UNDEFINED
            or self.users is not hikari.UNDEFINED
            or self.roles is not hikari.UNDEFINED
            or self.channels is not hikari.UNDEFINED
            or self.modal_values is not hikari.UNDEFINED
            or self.raw_perspective_bounds is not hikari.UNDEFINED
        )


class SettingsItem(ViewItem):
    @property
    def view(self) -> SettingsView:
        return super().view  # type: ignore


class BooleanButton(miru.Button, SettingsItem):
    """A boolean toggle button."""

    def __init__(
        self,
        *,
        state: bool,
        label: str,
        disabled: bool = False,
        row: t.Optional[int] = None,
        custom_id: t.Optional[str] = None,
    ) -> None:
        style = hikari.ButtonStyle.SUCCESS if state else hikari.ButtonStyle.DANGER
        emoji = "✔️" if state else "✖️"

        self.state = state

        super().__init__(style=style, label=label, emoji=emoji, disabled=disabled, row=row, custom_id=custom_id)

    async def callback(self, _: miru.ViewContext) -> None:
        self.state = not self.state
        assert self.label is not None

        self.style = hikari.ButtonStyle.SUCCESS if self.state else hikari.ButtonStyle.DANGER
        self.emoji = "✔️" if self.state else "✖️"
        self.view.value = SettingValue(boolean=self.state, text=self.label)
        self.view.last_item = self


class OptionButton(miru.Button, SettingsItem):
    """Button that sets view value to label."""

    async def callback(self, _: miru.ViewContext) -> None:
        assert self.label is not None
        self.view.value = SettingValue(text=self.label)
        self.view.last_item = self


class OptionsModal(miru.Modal):
    def __init__(
        self,
        view: SettingsView,
        title: str,
        *,
        custom_id: t.Optional[str] = None,
        timeout: t.Optional[float] = 300,
    ) -> None:
        super().__init__(title, custom_id=custom_id, timeout=timeout)
        self.view = view

    async def callback(self, context: miru.ModalContext) -> None:
        self.last_item = None
        self.view.value = SettingValue(modal_values=context.values)
        self.view._done_event.set()

    async def on_timeout(self) -> None:
        self.view.value = SettingValue()
        self.view._done_event.set()


class PerspectiveBoundsModal(miru.Modal):
    def __init__(
        self,
        view: miru.View,
        values: t.Dict[str, float],
        title: str,
        *,
        custom_id: t.Optional[str] = None,
        timeout: t.Optional[float] = 300,
    ) -> None:
        super().__init__(title, custom_id=custom_id, timeout=timeout)
        self.add_item(
            miru.TextInput(
                label="Toxicity",
                placeholder="Enter a floating point value...",
                custom_id="TOXICITY",
                value=str(values["TOXICITY"]),
                min_length=3,
                max_length=7,
            )
        )
        self.add_item(
            miru.TextInput(
                label="Severe Toxicity",
                placeholder="Enter a floating point value...",
                custom_id="SEVERE_TOXICITY",
                value=str(values["SEVERE_TOXICITY"]),
                min_length=3,
                max_length=7,
            )
        )
        self.add_item(
            miru.TextInput(
                label="Threat",
                placeholder="Enter a floating point value...",
                custom_id="THREAT",
                value=str(values["THREAT"]),
                min_length=3,
                max_length=7,
            )
        )
        self.add_item(
            miru.TextInput(
                label="Profanity",
                placeholder="Enter a floating point value...",
                custom_id="PROFANITY",
                value=str(values["PROFANITY"]),
                min_length=3,
                max_length=7,
            )
        )
        self.add_item(
            miru.TextInput(
                label="Insult",
                placeholder="Enter a floating point value...",
                custom_id="INSULT",
                value=str(values["INSULT"]),
                min_length=3,
                max_length=7,
            )
        )
        self.view = view

    async def callback(self, context: miru.ModalContext) -> None:
        self.last_item = None
        self._last_context = context
        self.view.value = SettingValue(raw_perspective_bounds={item.custom_id: value for item, value in context.values.items()})  # type: ignore
        self.view._input_event.set()
        self.view._input_event.clear()

    async def on_timeout(self) -> None:
        self.view.value = SettingValue()  # type: ignore
        self.view._input_event.set()
        self.view._input_event.clear()


class OptionsTextSelect(miru.TextSelect, SettingsItem):
    """Select that sets view value to first selected option's value."""

    def __init__(self, with_done: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.with_done = with_done

    async def callback(self, ctx: miru.ViewContext) -> None:
        self.view.value = SettingValue(text=self.values[0])
        self.view.last_item = self

        if self.with_done:
            await ctx.defer()


class OptionsRoleSelect(miru.RoleSelect, SettingsItem):
    def __init__(self, with_done: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.with_done = with_done

    async def callback(self, ctx: miru.ViewContext) -> None:
        self.view.value = SettingValue(roles=self.values or None)
        self.view.last_item = self

        if self.with_done:
            await ctx.defer()


class OptionsChannelSelect(miru.ChannelSelect, SettingsItem):
    def __init__(self, with_done: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.with_done = with_done

    async def callback(self, ctx: miru.ViewContext) -> None:
        self.view.value = SettingValue(channels=self.values)
        self.view.last_item = self

        if self.with_done:
            await ctx.defer()


class BackButton(OptionButton):
    """Go back to page that ctx.parent is set to."""

    def __init__(self, parent: str, **kwargs) -> None:
        super().__init__(style=hikari.ButtonStyle.PRIMARY, custom_id=parent, label="Back", emoji="⬅️")
        self.kwargs = kwargs

    async def callback(self, _: miru.ViewContext) -> None:
        self.view.last_item = self
        self.view.value = SettingValue()
        self.view._done_event.set()  # Trigger the done event in case the view is waiting for one
        self.view._done_event.clear()
        await self.view.menu_actions[self.custom_id](**self.kwargs)


class DoneButton(miru.Button, SettingsItem):
    """Button that signals to the view the action being waited for is done."""

    def __init__(self, parent: str, **kwargs) -> None:
        super().__init__(style=hikari.ButtonStyle.SUCCESS, custom_id=f"done:{parent}", label="Done", emoji="✔️")
        self.kwargs = kwargs

    async def callback(self, _: miru.ViewContext) -> None:
        self.view.last_item = self
        self.view.value.is_done = True  # Confirm that all values are final
        self.view._done_event.set()
        self.view._done_event.clear()


class QuitButton(OptionButton):
    """Quit settings, delete message."""

    def __init__(self) -> None:
        super().__init__(style=hikari.ButtonStyle.DANGER, label="Quit", emoji="⬅️")

    async def callback(self, _: miru.ViewContext) -> None:
        self.view.last_item = self
        self.view.value = SettingValue()
        await self.view.menu_actions["Quit"]()


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
