from __future__ import annotations

import typing as t

import hikari
import lightbulb

import etc.const as const
from models.context import SnedSlashContext
from models.plugin import SnedPlugin

if t.TYPE_CHECKING:
    from models import SnedBot


help = SnedPlugin("Help")


help_embeds = {
    # Default no topic help
    None: hikari.Embed(
        title="ℹ️ __Help__",
        description="""**Welcome to Sned Help!**
            
To get started with using the bot, simply press `/` to reveal all commands! If you would like to get help about a specific topic, use `/help topic_name`.

If you need assistance, found a bug, or just want to hang out, please join our [support server](https://discord.gg/KNKr8FPmJa)!

Thank you for using Sned!""",
        color=const.EMBED_BLUE,
    ),
    # Default no topic help for people with manage guild perms
    "admin_home": hikari.Embed(
        title="ℹ️ __Help__",
        description="""**Welcome to Sned Help!**
            
To get started with using the bot, simply press `/` to reveal all commands! If you would like to get help about a specific topic, use `/help topic_name`.

You may begin configuring the bot via the `/settings` command, which shows all relevant settings & lets you modify them.

If you need assistance, found a bug, or just want to hang out, please join our [support server](https://discord.gg/KNKr8FPmJa)!

Thank you for using Sned!""",
        color=const.EMBED_BLUE,
    ),
    "time-formatting": hikari.Embed(
        title="ℹ️ __Help: Time Formatting__",
        description="""This help article aims to familiarize you with the various ways you can input time into bot commands.

**Dates:**
`2022-03-04 23:43`
`04/03/2022 23:43`
`2022/04/03 11:43PM`
`...`

**Relative:**
`in 10 minutes`
`tomorrow at 5AM`
`next week`
`2 days ago`
`...`

**ℹ️ Note:**
Absolute time-conversion may require the bot to be aware of your timezone. You can set your timezone via the `/timezone` command, if you wish.
""",
        color=const.EMBED_BLUE,
    ),
    "permissions": hikari.Embed(
        title="ℹ️ __Help: Permissions__",
        description="""Command permissions for the bot are managed directly through Discord. To access them, navigate to:
```Server Settings > Integrations > Sned```
Here you may configure permissions per-command or on a global basis, as you see fit.""",
        color=const.EMBED_BLUE,
    ).set_image("https://cdn.discordapp.com/attachments/836300326172229672/949047433038544896/unknown.png"),
    "configuration": hikari.Embed(
        title="ℹ️ ___Help: Configuration__",
        description="""To configure the bot, use the `/settings` command. This will open up an interactive menu for you to change the different properties of the bot, enable/disable features, or tailor them to your liking.
If you need any assistance in configuring the bot, do not hesitate to join our [support server](https://discord.gg/KNKr8FPmJa)!""",
        color=const.EMBED_BLUE,
    ),
}


@help.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option(
    "topic",
    "A specific topic to get help about.",
    required=False,
    choices=["time-formatting", "configuration", "permissions"],
)
@lightbulb.command("help", "Get help regarding various subjects of the bot's functionality.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def help_cmd(ctx: SnedSlashContext, topic: t.Optional[str] = None) -> None:
    if ctx.member:
        topic = (
            topic or "admin_home"
            if (lightbulb.utils.permissions_for(ctx.member) & hikari.Permissions.MANAGE_GUILD)
            else topic
        )
    await ctx.respond(embed=help_embeds[topic])


def load(bot: SnedBot) -> None:
    bot.add_plugin(help)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(help)


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
