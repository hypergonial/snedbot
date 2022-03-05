from __future__ import annotations

import typing as t

import hikari
import lightbulb

import etc.constants as const
from models.context import SnedSlashContext

if t.TYPE_CHECKING:
    from models import SnedBot


help = lightbulb.Plugin("Help")


help_embeds = {
    None: hikari.Embed(
        title="ℹ️ __Help__",
        description="""**Welcome to Sned Help!**
            
To get started with using the bot, simply press `/` to reveal all commands! If you would like to get help about a specific topic, use `/help topic_name`.

If you're an administrator, you may begin configuring the bot via the `/settings` command.

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
Relative time-conversion may require the bot to be aware of your timezone. You can set your timezone via the `/timezone` command, if you wish.
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
If you need any assistance in configuring the bot, do not hesitate to join our [suuport server](https://discord.gg/KNKr8FPmJa)!""",
        color=const.EMBED_BLUE,
    ),
}


@help.command()
@lightbulb.option(
    "topic",
    "A specific topic to get help about.",
    required=False,
    choices=["time-formatting", "permissions", "configuration"],
)
@lightbulb.command("help", "Get help regarding various subjects of the bot's functionality.")
@lightbulb.implements(lightbulb.SlashCommand)
async def help_cmd(ctx: SnedSlashContext) -> None:
    await ctx.respond(embed=help_embeds[ctx.options.topic])


def load(bot: SnedBot) -> None:
    bot.add_plugin(help)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(help)
