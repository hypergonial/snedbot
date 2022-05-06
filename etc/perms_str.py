import hikari

perms_str = {
    hikari.Permissions.CREATE_INSTANT_INVITE: "Create Invites",
    hikari.Permissions.STREAM: "Go Live",
    hikari.Permissions.SEND_TTS_MESSAGES: "Send TTS Messages",
    hikari.Permissions.MANAGE_MESSAGES: "Manage Messages",
    hikari.Permissions.MENTION_ROLES: "Mention @everyone and all roles",
    hikari.Permissions.USE_EXTERNAL_EMOJIS: "Use external emojies",
    hikari.Permissions.VIEW_GUILD_INSIGHTS: "View Insights",
    hikari.Permissions.CONNECT: "Connect to Voice",
    hikari.Permissions.SPEAK: "Speak in Voice",
    hikari.Permissions.MUTE_MEMBERS: "Mute Others in Voice",
    hikari.Permissions.DEAFEN_MEMBERS: "Deafen Others in Voice",
    hikari.Permissions.MOVE_MEMBERS: "Move Others in Voice",
    hikari.Permissions.REQUEST_TO_SPEAK: "Request to Speak in Stage",
    hikari.Permissions.START_EMBEDDED_ACTIVITIES: "Start Activities",
    hikari.Permissions.MODERATE_MEMBERS: "Timeout Members",
}


def get_perm_str(perm: hikari.Permissions) -> str:
    if perm_str := perms_str.get(perm):
        return perm_str

    assert perm.name is not None
    return perm.name.replace("_", " ").title()


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
