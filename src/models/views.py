import typing as t

import hikari
import miru
from miru.ext import nav

from src.etc import const


class StopSelect(miru.TextSelect):
    """A select that stops the view after interaction."""

    async def callback(self, _: miru.ViewContext) -> None:
        self.view.stop()


class AuthorOnlyView(miru.View):
    """A navigator that only works for the user who invoked it."""

    def __init__(
        self, author: hikari.PartialUser | hikari.Snowflakeish, *, timeout: float | None = 120, autodefer: bool = True
    ) -> None:
        super().__init__(timeout=timeout, autodefer=autodefer)
        self._author_id = hikari.Snowflake(author)

    async def view_check(self, ctx: miru.ViewContext) -> bool:
        if ctx.user.id != self._author_id:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Oops!",
                    description="A magical barrier is stopping you from interacting with this component menu!",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        return ctx.user.id == self._author_id


class SnedNavigator(nav.NavigatorView):
    def __init__(
        self,
        *,
        pages: list[str | hikari.Embed | t.Sequence[hikari.Embed] | nav.Page],
        items: list[nav.NavItem] | None = None,
        timeout: float | None = 120.0,
        autodefer: bool = True,
    ) -> None:
        items = items or [
            nav.FirstButton(emoji=const.EMOJI_FIRST),
            nav.PrevButton(emoji=const.EMOJI_PREV),
            nav.IndicatorButton(),
            nav.NextButton(emoji=const.EMOJI_NEXT),
            nav.LastButton(emoji=const.EMOJI_LAST),
        ]
        super().__init__(pages=pages, items=items, timeout=timeout, autodefer=autodefer)


class AuthorOnlyNavigator(SnedNavigator):
    """A navigator that only works for the user who invoked it."""

    def __init__(
        self,
        author: hikari.PartialUser | hikari.Snowflakeish,
        *,
        pages: list[str | hikari.Embed | t.Sequence[hikari.Embed] | nav.Page],
        items: list[nav.NavItem] | None = None,
        timeout: float | None = 300.0,
        autodefer: bool = True,
    ) -> None:
        self._author_id = hikari.Snowflake(author)

        super().__init__(pages=pages, items=items, timeout=timeout, autodefer=autodefer)

    async def view_check(self, ctx: miru.ViewContext) -> bool:
        if ctx.user.id != self._author_id:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Oops!",
                    description="A magical barrier is stopping you from interacting with this navigation menu!",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        return ctx.user.id == self._author_id


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
