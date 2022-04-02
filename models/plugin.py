from __future__ import annotations

import typing as t

import lightbulb

if t.TYPE_CHECKING:
    from models.bot import SnedBot


class SnedPlugin(lightbulb.Plugin):
    @property
    def app(self) -> SnedBot:
        return super().app  # type: ignore

    @app.setter
    def app(self, val: SnedBot) -> None:
        self._app = val
        self.create_commands()

    @property
    def bot(self) -> SnedBot:
        return super().bot  # type: ignore
