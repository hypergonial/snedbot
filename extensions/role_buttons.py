import logging
from typing import List, Optional

import hikari
import lightbulb
import miru
from objects.models.bot import SnedBot
from objects import models

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
        if not interaction.guild_id:
            return

        try:
            if self.role.id in interaction.member.role_ids:
                await interaction.member.remove_role(self.role, reason=f"Removed by role-button (ID: {self.entry_id})")
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


@role_buttons.command()
@lightbulb.command("rolebutton", "Commands relating to rolebuttons.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def rolebutton(ctx: lightbulb.SlashContext) -> None:
    pass


@rolebutton.child()
@lightbulb.command("list", "List all registered rolebuttons on this server.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_list(ctx: lightbulb.SlashContext) -> None:
    records = await ctx.app.db_cache.get(table="button_roles", guild_id=ctx.guild.id)

    if not records:
        embed = hikari.Embed(
            title="❌ Error: No role-buttons",
            description="There are no role-buttons for this server.",
            color=ctx.app.error_color,
        )
        return await ctx.channel.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    paginator = lightbulb.utils.Paginator(max_chars=500)
    for record in records:
        role = ctx.app.cache.get_role(record["role_id"])
        channel = ctx.app.cache.get_guild_channel(record["channel_id"])

        if role and channel:
            paginator.add_line(f"**#{record['entry_id']}** - {channel.mention} - {role.mention}")

        else:
            paginator.add_line(f"**#{record['entry_id']}** - C: {record['channel_id']} - R: {record['role_id']}")

        embeds = []
        for page in paginator.build_pages():
            embed = hikari.Embed(
                title="Rolebuttons on this server:",
                description=page,
                color=ctx.app.embed_blue,
            )
            embeds.append(embed)

        navigator = models.AuthorOnlyNavigator(ctx, pages=embeds)
        await navigator.send(ctx.interaction)


@rolebutton.child()
@lightbulb.option("button_id", "The ID of the rolebutton to delete. You can get this via /rolebutton list")
@lightbulb.command("delete", "Delete a rolebutton.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_del(ctx: lightbulb.SlashContext) -> None:
    records = await ctx.app.db_cache.get(table="button_roles", guild_id=ctx.guild.id, entry_id=ctx.options.button_id)

    if not records:
        embed = hikari.Embed(
            title="❌ Not found",
            description="There is no rolebutton by that ID. Check your existing rolebuttons via `/rolebutton list`",
            color=ctx.app.error_color,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


def load(bot: SnedBot) -> None:
    logging.info("Adding plugin: Role-Buttons")
    bot.add_plugin(role_buttons)


def unload(bot: SnedBot) -> None:
    logging.info("Removing plugin: Role-Buttons")
    bot.remove_plugin(role_buttons)
