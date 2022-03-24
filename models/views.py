from typing import List
from typing import Optional
from typing import Union

import hikari
import lightbulb
import miru
from miru.ext import nav

from etc import constants as const


class StopSelect(miru.Select):
    """
    A select that stops the view after interaction.
    """

    async def callback(self, context: miru.Context) -> None:
        self.view.stop()


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
                color=const.ERROR_COLOR,
            )
            await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        return ctx.user.id == self.lctx.author.id


class SnedNavigator(nav.NavigatorView):
    def __init__(
        self,
        *,
        pages: List[Union[str, hikari.Embed]],
        timeout: Optional[float] = 120,
        autodefer: bool = True,
    ) -> None:
        buttons = [
            nav.FirstButton(emoji=const.EMOJI_FIRST),
            nav.PrevButton(emoji=const.EMOJI_PREV),
            nav.IndicatorButton(),
            nav.NextButton(emoji=const.EMOJI_NEXT),
            nav.LastButton(emoji=const.EMOJI_LAST),
        ]
        super().__init__(pages=pages, buttons=buttons, timeout=timeout, autodefer=autodefer)


class AuthorOnlyNavigator(SnedNavigator):
    """
    A navigator that only works for the user who invoked it.
    """

    def __init__(
        self,
        lctx: lightbulb.Context,
        *,
        pages: List[Union[str, hikari.Embed]],
        timeout: Optional[float] = 120,
        autodefer: bool = True,
    ) -> None:
        self.lctx = lctx

        super().__init__(pages=pages, timeout=timeout, autodefer=autodefer)

    async def view_check(self, ctx: miru.Context) -> bool:
        if ctx.user.id != self.lctx.author.id:
            embed = hikari.Embed(
                title="❌ Oops!",
                description="A magical barrier is stopping you from interacting with this navigation menu!",
                color=const.ERROR_COLOR,
            )
            await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        return ctx.user.id == self.lctx.author.id
