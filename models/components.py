from __future__ import annotations

import typing as t

import hikari
import miru

if t.TYPE_CHECKING:
    from extensions.settings import SettingsView


class BooleanButton(miru.Button):
    """A boolean toggle button."""

    def __init__(
        self,
        *,
        state: bool,
        label: t.Optional[str] = None,
        disabled: bool = False,
        row: t.Optional[int] = None,
        custom_id: t.Optional[str] = None,
    ) -> None:
        style = hikari.ButtonStyle.SUCCESS if state else hikari.ButtonStyle.DANGER
        emoji = "✔️" if state else "✖️"

        self.state = state

        super().__init__(style=style, label=label, emoji=emoji, disabled=disabled, row=row, custom_id=custom_id)

    async def callback(self, context: miru.ViewContext) -> None:
        self.state = not self.state

        self.style = hikari.ButtonStyle.SUCCESS if self.state else hikari.ButtonStyle.DANGER
        self.emoji = "✔️" if self.state else "✖️"
        self.view.value = (self.label, self.state)
        self.view.last_item = self
        self.view.last_ctx = context
        self.view.input_event.set()


class OptionButton(miru.Button):
    """Button that sets view value to label."""

    async def callback(self, context: miru.ViewContext) -> None:
        self.view.value = self.label
        self.view.last_item = self
        self.view.last_ctx = context
        self.view.input_event.set()


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
        self.view.last_ctx = context
        self.last_item = None
        self.view.value = context.values
        self.view.input_event.set()

    async def on_timeout(self) -> None:
        self.view.value = None
        self.view.input_event.set()


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
        self.view.last_ctx = context
        self.last_item = None
        self.view.value = {item.custom_id: value for item, value in context.values.items()}
        self.view.input_event.set()

    async def on_timeout(self) -> None:
        self.view.value = None
        self.view.input_event.set()


class OptionsSelect(miru.Select):
    """Select that sets view value to first selected option's value."""

    async def callback(self, context: miru.ViewContext) -> None:
        self.view.value = self.values[0]
        self.view.last_item = self
        self.view.last_ctx = context
        self.view.input_event.set()


class BackButton(OptionButton):
    """Go back to page that ctx.parent is set to."""

    def __init__(self, parent: str, **kwargs) -> None:
        super().__init__(style=hikari.ButtonStyle.PRIMARY, custom_id=parent, label="Back", emoji="⬅️")
        self.kwargs = kwargs

    async def callback(self, context: miru.ViewContext) -> None:
        self.view.last_ctx = context
        self.view.last_item = self
        self.view.value = None
        self.view.input_event.set()
        await self.view.menu_actions[self.custom_id](**self.kwargs)


class QuitButton(OptionButton):
    """Quit settings, delete message."""

    def __init__(self) -> None:
        super().__init__(style=hikari.ButtonStyle.DANGER, label="Quit", emoji="⬅️")

    async def callback(self, context: miru.ViewContext) -> None:
        self.view.last_ctx = context
        self.view.last_item = self
        self.view.value = None
        await self.view.menu_actions["Quit"]()
        self.view.input_event.set()


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
