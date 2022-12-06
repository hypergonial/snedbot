import asyncio
import logging

import hikari
import lightbulb

from etc import const, get_perm_str
from models import SnedSlashContext
from models.bot import SnedBot
from models.plugin import SnedPlugin

logger = logging.getLogger(__name__)

troubleshooter = SnedPlugin("Troubleshooter")

# Find perms issues
# Find automod config issues
# Find missing channel perms issues
# ...

REQUIRED_PERMISSIONS = (
    hikari.Permissions.VIEW_AUDIT_LOG
    | hikari.Permissions.MANAGE_ROLES
    | hikari.Permissions.KICK_MEMBERS
    | hikari.Permissions.BAN_MEMBERS
    | hikari.Permissions.MANAGE_CHANNELS
    | hikari.Permissions.MANAGE_THREADS
    | hikari.Permissions.MANAGE_NICKNAMES
    | hikari.Permissions.CHANGE_NICKNAME
    | hikari.Permissions.READ_MESSAGE_HISTORY
    | hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.CREATE_PUBLIC_THREADS
    | hikari.Permissions.CREATE_PRIVATE_THREADS
    | hikari.Permissions.SEND_MESSAGES_IN_THREADS
    | hikari.Permissions.EMBED_LINKS
    | hikari.Permissions.ATTACH_FILES
    | hikari.Permissions.MENTION_ROLES
    | hikari.Permissions.USE_EXTERNAL_EMOJIS
    | hikari.Permissions.MODERATE_MEMBERS
    | hikari.Permissions.MANAGE_MESSAGES
    | hikari.Permissions.ADD_REACTIONS
)

# Explain why the bot requires the perm
PERM_DESCRIPTIONS = {
    hikari.Permissions.VIEW_AUDIT_LOG: "Required in logs to fill in details such as who the moderator in question was, or the reason of the action.",
    hikari.Permissions.MANAGE_ROLES: "Required to give users roles via role-buttons, and for the `/role` command to function.",
    hikari.Permissions.MANAGE_CHANNELS: "Used by `/slowmode` to set a custom slow mode duration for the channel.",
    hikari.Permissions.MANAGE_THREADS: "Used by `/slowmode` to set a custom slow mode duration for the thread.",
    hikari.Permissions.MANAGE_NICKNAMES: "Used by `/deobfuscate` to deobfuscate other user's nicknames.",
    hikari.Permissions.KICK_MEMBERS: "Required to use the `/kick` command and let auto-moderation actions kick users.",
    hikari.Permissions.BAN_MEMBERS: "Required to use the `/ban`, `/softban`, `/massban` command and let auto-moderation actions ban users.",
    hikari.Permissions.CHANGE_NICKNAME: "Required for the `/setnick` command.",
    hikari.Permissions.READ_MESSAGE_HISTORY: "Required for auto-moderation, starboard, `/edit`, and other commands that may require to fetch messages.",
    hikari.Permissions.VIEW_CHANNEL: "Required for auto-moderation, starboard, `/edit`, and other commands that may require to fetch messages.",
    hikari.Permissions.SEND_MESSAGES: "Required to send messages independently of commands, this includes `/echo`, `/edit`, logging, starboard, reports and auto-moderation.",
    hikari.Permissions.CREATE_PUBLIC_THREADS: "Required for the bot to access and manage threads.",
    hikari.Permissions.CREATE_PRIVATE_THREADS: "Required for the bot to access and manage threads.",
    hikari.Permissions.SEND_MESSAGES_IN_THREADS: "Required for the bot to access and manage threads.",
    hikari.Permissions.EMBED_LINKS: "Required for the bot to create embeds to display content, without this you may not see any responses from the bot, including this one :)",
    hikari.Permissions.ATTACH_FILES: "Required for the bot to attach files to a message, for example to send a list of users to be banned in `/massban`.",
    hikari.Permissions.MENTION_ROLES: "Required for the bot to always be able to mention roles, for example when reporting users. The bot will **never** mention @everyone or @here.",
    hikari.Permissions.USE_EXTERNAL_EMOJIS: "Required to display certain content with custom emojies, typically to better illustrate certain content.",
    hikari.Permissions.ADD_REACTIONS: "This permission is used for creating giveaways and adding the initial reaction to the giveaway message.",
    hikari.Permissions.MODERATE_MEMBERS: "Required to use the `/timeout` command and let auto-moderation actions timeout users.",
    hikari.Permissions.MANAGE_MESSAGES: "This permission is required to delete other user's messages, for example in the case of auto-moderation.",
}


@troubleshooter.command
@lightbulb.app_command_permissions(hikari.Permissions.MANAGE_GUILD, dm_enabled=False)
@lightbulb.command("troubleshoot", "Diagnose and locate common configuration issues.")
@lightbulb.implements(lightbulb.SlashCommand)
async def troubleshoot(ctx: SnedSlashContext) -> None:
    assert ctx.interaction.app_permissions is not None

    missing_perms = ~ctx.interaction.app_permissions & REQUIRED_PERMISSIONS
    content = []

    if missing_perms is not hikari.Permissions.NONE:
        content.append("**Missing Permissions:**")
        content += [
            f"❌ **{get_perm_str(perm)}**: {desc}" for perm, desc in PERM_DESCRIPTIONS.items() if missing_perms & perm
        ]

    if not content:
        embed = hikari.Embed(
            title="✅ No problems found!",
            description="If you believe there is an issue with Sned, found a bug, or simply have a question, please join the [support server!](https://discord.gg/KNKr8FPmJa)",
            color=const.EMBED_GREEN,
        )
    else:
        content = "\n".join(content)
        embed = hikari.Embed(
            title="Uh Oh!",
            description=f"It looks like there may be some issues with the configuration. Please review the list below!\n\n{content}\n\nIf you need any assistance resolving these issues, please join the [support server!](https://discord.gg/KNKr8FPmJa)",
            color=const.ERROR_COLOR,
        )

    await ctx.mod_respond(embed=embed)


def load(bot: SnedBot) -> None:
    bot.add_plugin(troubleshooter)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(troubleshooter)


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
