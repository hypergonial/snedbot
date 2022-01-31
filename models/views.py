import miru
from miru.ext import nav
from typing import List, Union, Optional
import hikari
import lightbulb


class AuthorOnlyView(miru.View):
    """
    A navigator that only works for the user who invoked it.
    """

    def __init__(self, lctx: lightbulb.Context, *, timeout: Optional[float] = 120, autodefer: bool = True) -> None:
        super().__init__(timeout=timeout, autodefer=autodefer)
        self.lctx = lctx

    async def view_check(self, ctx: miru.Context) -> bool:
        if ctx.user.id != self.lctx.author.id:
            embed = hikari.Embed(
                title="❌ Oops!",
                description="A magical barrier is stopping you from interacting with this component menu!",
                color=self.lctx.app.error_color,
            )
            await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        return ctx.user.id == self.lctx.author.id


class AuthorOnlyNavigator(nav.NavigatorView):
    """
    A navigator that only works for the user who invoked it.
    """

    def __init__(
        self,
        lctx: lightbulb.Context,
        *,
        pages: List[Union[str, hikari.Embed]],
        buttons: Optional[List[nav.NavButton[nav.NavigatorView]]] = None,
        timeout: Optional[float] = 120,
        autodefer: bool = True
    ) -> None:
        self.lctx = lctx
        super().__init__(pages=pages, buttons=buttons, timeout=timeout, autodefer=autodefer)

    async def view_check(self, ctx: miru.Context) -> bool:
        if ctx.user.id != self.lctx.author.id:
            embed = hikari.Embed(
                title="❌ Oops!",
                description="A magical barrier is stopping you from interacting with this navigation menu!",
                color=ctx.app.error_color,
            )
            await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        return ctx.user.id == self.lctx.author.id
