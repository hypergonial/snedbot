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
