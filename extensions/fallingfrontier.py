import hikari
import lightbulb

from config import Config
from models.bot import SnedBot
from models.plugin import SnedPlugin

ff = SnedPlugin("Falling Frontier")
ff.default_enabled_guilds = Config().DEBUG_GUILDS or (684324252786360476, 813803567445049414)


@ff.listener(hikari.GuildMessageCreateEvent)
async def hydrate_autoresponse(event: hikari.GuildMessageCreateEvent) -> None:
    if event.guild_id not in (684324252786360476, 813803567445049414):
        return

    if event.content and event.content == "Everyone this is your daily reminder to stay hydrated!":
        await event.message.respond("<:FoxHydrate:851099802527072297>")


def load(bot: SnedBot) -> None:
    bot.add_plugin(ff)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(ff)


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
