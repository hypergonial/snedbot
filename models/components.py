import miru
import hikari
import typing as t


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
        self.view.last_ctx = context
        self.view.input_event.set()


class OptionButton(miru.Button):
    """Button that sets view value to label."""

    async def callback(self, context: miru.ViewContext) -> None:
        self.view.value = self.label
        self.view.last_ctx = context
        self.view.input_event.set()


class OptionsSelect(miru.Select):
    """Select that sets view value to first selected option's value."""

    async def callback(self, context: miru.ViewContext) -> None:

        self.view.value = self.values[0]
        self.view.last_ctx = context
        self.view.input_event.set()


class BackButton(OptionButton):
    """Go back to page that ctx.parent is set to."""

    def __init__(self, parent: str) -> None:
        super().__init__(style=hikari.ButtonStyle.PRIMARY, custom_id=parent, label="Back", emoji="⬅️")

    async def callback(self, context: miru.ViewContext) -> None:
        self.view.last_ctx = context
        self.view.value = None
        self.view.input_event.set()
        await self.view.menu_actions[self.custom_id]()


class QuitButton(OptionButton):
    """Quit settings, delete message."""

    def __init__(self) -> None:
        super().__init__(style=hikari.ButtonStyle.DANGER, label="Quit", emoji="⬅️")

    async def callback(self, context: miru.ViewContext) -> None:
        self.view.last_ctx = context
        self.view.value = None
        await self.view.menu_actions["Quit"]()
        self.view.input_event.set()
