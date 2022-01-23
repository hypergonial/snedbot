import asyncio
import logging
from typing import List, Optional

import hikari
import lightbulb
import miru
from hikari.errors import ForbiddenError, HTTPError
from objects.models.bot import SnedBot

logger = logging.getLogger(__name__)

role_buttons = lightbulb.Plugin("Role-Buttons")

button_styles = {
    "Blurple": hikari.ButtonStyle.PRIMARY,
    "Grey": hikari.ButtonStyle.SECONDARY,
    "Green": hikari.ButtonStyle.SUCCESS,
    "Red": hikari.ButtonStyle.DANGER,
}


class PersistentRoleView(miru.View):
    def __init__(self, app: hikari.GatewayBot, buttons: List[miru.Button]) -> None:
        super().__init__(app, timeout=None)
        for button in buttons:
            self.add_item(button)


class RoleButton(miru.Button):
    def __init__(
        self,
        entry_id: int,
        role: hikari.Role,
        emoji: hikari.Emoji,
        style: hikari.ButtonStyle,
        label: Optional[str] = None,
    ):
        super().__init__(style=style, label=label, emoji=emoji, custom_id=f"{entry_id}:{role.id}")
        self.entry_id: int = entry_id
        self.role: hikari.Role = role

    async def callback(self, interaction: miru.Interaction) -> None:
        """
        Add or remove the role this button was instantiated with.
        """
        if interaction.guild_id:
            try:
                if self.role.id in interaction.member.role_ids:
                    await interaction.member.remove_role(
                        self.role, reason=f"Removed by role-button (ID: {self.entry_id})"
                    )
                    embed = hikari.Embed(
                        title="✅ Role removed",
                        description=f"Removed role: {self.role.mention}",
                        color=0x77B255,
                    )
                    await interaction.send_message(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

                else:
                    await interaction.member.add_role(self.role, reason=f"Granted by role-button (ID: {self.entry_id})")
                    embed = hikari.Embed(
                        title="✅ Role added",
                        description=f"Added role: {self.role.mention}",
                        color=0x77B255,
                    )
                    embed.set_footer(text="If you would like it removed, click the button again!")
                    await interaction.send_message(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

            except (hikari.ForbiddenError, hikari.HTTPError):
                embed = hikari.Embed(
                    title="❌ Insufficient permissions",
                    description="Failed adding role due to an issue with permissions and/or role hierarchy! Please contact an administrator!",
                    color=0xFF0000,
                )
                await interaction.send_message(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@role_buttons.listener()
async def start_rolebuttons(event: hikari.StartedEvent) -> None:
    """
    Start up listeners for all role-buttons after application restart
    """
    app: SnedBot = event.app
    logger.info("Starting up listeners for persistent role-buttons...")
    records = await app.pool.fetch("""SELECT * FROM button_roles""")

    add_to_persistent_views = {}
    count = 0

    for record in records:
        role = app.cache.get_role(record.get("role_id"))
        emoji = hikari.Emoji.parse(record.get("emoji"))
        button = RoleButton(
            entry_id=record.get("entry_id"),
            role=role,
            label=record.get("buttonlabel"),
            style=button_styles[record.get("buttonstyle")],
            emoji=emoji,
        )
        if record.get("msg_id") not in add_to_persistent_views.keys():
            add_to_persistent_views[record.get("msg_id")] = [button]
        else:
            add_to_persistent_views[record.get("msg_id")].append(button)
        count += 1

    for msg_id, buttons in add_to_persistent_views.items():
        # Use message_id optionally for improved accuracy
        view = PersistentRoleView(buttons)
        view.start_listener(message_id=msg_id)

    logger.info(f"Started listeners for {count} button-roles!")


def load(bot: SnedBot) -> None:
    logging.info("Adding plugin: Role-Buttons")
    bot.add_plugin(role_buttons)


def unload(bot: SnedBot) -> None:
    logging.info("Removing plugin: Role-Buttons")
    bot.remove_plugin(role_buttons)
