import miru
from miru.ext import nav
from typing import List, Union, Optional
import hikari
import lightbulb


class AuthorOnlyView(miru.View):
    """
    A navigator that only works for the user who invoked it.
    """

    def __init__(self, ctx: lightbulb.Context, *, timeout: Optional[float] = 120, autodefer: bool = True) -> None:
        super().__init__(ctx.app, timeout=timeout, autodefer=autodefer)

    async def view_check(self, interaction: miru.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            embed = hikari.Embed(
                title="❌ Oops!",
                description="A magical barrier is stopping you from interacting with this component menu!",
                color=self.ctx.app.error_color,
            )
            await interaction.send_message(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        return interaction.user.id == self.ctx.author.id


class AuthorOnlyNavigator(nav.NavigatorView):
    """
    A navigator that only works for the user who invoked it.
    """

    def __init__(
        self,
        ctx: lightbulb.Context,
        *,
        pages: List[Union[str, hikari.Embed]],
        buttons: Optional[List[nav.NavButton[nav.NavigatorView]]] = None,
        timeout: Optional[float] = 120,
        autodefer: bool = True
    ) -> None:
        self.ctx = ctx
        super().__init__(ctx.app, pages=pages, buttons=buttons, timeout=timeout, autodefer=autodefer)

    async def view_check(self, interaction: miru.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            embed = hikari.Embed(
                title="❌ Oops!",
                description="A magical barrier is stopping you from interacting with this navigation menu!",
                color=self.ctx.app.error_color,
            )
            await interaction.send_message(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        return interaction.user.id == self.ctx.author.id
