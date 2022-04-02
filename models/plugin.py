from __future__ import annotations

import typing as t

import lightbulb

if t.TYPE_CHECKING:
    from models.bot import SnedBot


class SnedPlugin(lightbulb.Plugin):
    @property
    def app(self) -> SnedBot:
        return super().app  # type: ignore

    @property
    def bot(self) -> SnedBot:
        return super().bot  # type: ignore
