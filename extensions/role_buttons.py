import logging
from typing import List, Optional

import hikari
import lightbulb
import miru
from models import SnedBot
import models
from models import SnedSlashContext

logger = logging.getLogger(__name__)

role_buttons = lightbulb.Plugin("Role-Buttons")

button_styles = {
    "Blurple": hikari.ButtonStyle.PRIMARY,
    "Grey": hikari.ButtonStyle.SECONDARY,
    "Green": hikari.ButtonStyle.SUCCESS,
    "Red": hikari.ButtonStyle.DANGER,
}


class PersistentRoleView(miru.View):
    def __init__(self, buttons: List[miru.Button]) -> None:
        super().__init__(timeout=None)
        for button in buttons:
            self.add_item(button)


class RoleButton(miru.Button):
    def __init__(
        self,
        *,
        entry_id: int,
        emoji: hikari.Emoji,
        style: hikari.ButtonStyle,
        label: Optional[str] = None,
        role: Optional[hikari.Role] = None,
    ):
        if not role:
            self.orphaned = True
        else:
            self.orphaned = False

        super().__init__(style=style, label=label, emoji=emoji, custom_id=f"{entry_id}:{role.id}")
        self.entry_id: int = entry_id
        self.role: hikari.Role = role

    async def callback(self, ctx: miru.Context) -> None:
        """
        Add or remove the role this button was instantiated with.
        """
        if not ctx.guild_id:
            return

        if self.orphaned:
            embed = hikari.Embed(
                title="❌ Orphaned",
                description="The role this button was pointing to was deleted! Please notify an administrator!",
                color=0xFF0000,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        try:
            if self.role.id in ctx.member.role_ids:
                await ctx.member.remove_role(self.role, reason=f"Removed by role-button (ID: {self.entry_id})")
                embed = hikari.Embed(
                    title="✅ Role removed",
                    description=f"Removed role: {self.role.mention}",
                    color=0x77B255,
                )
                await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

            else:
                await ctx.member.add_role(self.role, reason=f"Granted by role-button (ID: {self.entry_id})")
                embed = hikari.Embed(
                    title="✅ Role added",
                    description=f"Added role: {self.role.mention}",
                    color=0x77B255,
                )
                embed.set_footer(text="If you would like it removed, click the button again!")
                await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        except (hikari.ForbiddenError, hikari.HTTPError):
            embed = hikari.Embed(
                title="❌ Insufficient permissions",
                description="Failed adding role due to an issue with permissions and/or role hierarchy! Please contact an administrator!",
                color=0xFF0000,
            )
            await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@role_buttons.listener(lightbulb.LightbulbStartedEvent)
async def start_rolebuttons(event: lightbulb.LightbulbStartedEvent) -> None:
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
            style=button_styles[record.get("buttonstyle") or "Grey"],
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
        view.start_listener(message=msg_id)

    logger.info(f"Started listeners for {count} role-buttons!")


@role_buttons.command()
@lightbulb.command("rolebutton", "Commands relating to rolebuttons.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def rolebutton(ctx: SnedSlashContext) -> None:
    pass


@rolebutton.child()
@lightbulb.command("list", "List all registered rolebuttons on this server.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_list(ctx: SnedSlashContext) -> None:
    records = await ctx.app.db_cache.get(table="button_roles", guild_id=ctx.guild_id)

    if not records:
        embed = hikari.Embed(
            title="❌ Error: No role-buttons",
            description="There are no role-buttons for this server.",
            color=ctx.app.error_color,
        )
        return await ctx.channel.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    paginator = lightbulb.utils.StringPaginator(max_chars=500)
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
@lightbulb.option(
    "button_id",
    "The ID of the rolebutton to delete. You can get this via /rolebutton list",
)
@lightbulb.command("delete", "Delete a rolebutton.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_del(ctx: SnedSlashContext) -> None:
    records = await ctx.app.db_cache.get(table="button_roles", guild_id=ctx.guild_id, entry_id=ctx.options.button_id)

    if not records:
        embed = hikari.Embed(
            title="❌ Not found",
            description="There is no rolebutton by that ID. Check your existing rolebuttons via `/rolebutton list`",
            color=ctx.app.error_color,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    await ctx.app.pool.execute(
        """DELETE FROM button_roles WHERE guild_id = $1 AND entry_id = $2""",
        ctx.guild_id,
        ctx.options.button_id,
    )
    await ctx.app.db_cache.refresh(table="button_roles", guild_id=ctx.guild_id)

    try:
        message = await ctx.app.rest.fetch_message(records[0]["channel_id"], records[0]["msg_id"])
    except hikari.NotFoundError:
        pass
    else:
        records = await ctx.app.db_cache.get(table="button_roles", guild_id=ctx.guild_id, msg_id=message.id)
        buttons = []
        if not records:
            return
        # Re-sync rolebuttons with db if message still exists
        for record in records:
            emoji = hikari.Emoji.parse(record.get("emoji"))
            role = ctx.app.cache.get_role(record.get("role_id"))
            if not role:
                continue
            buttons.append(
                RoleButton(
                    entry_id=record.get("entry_id"),
                    role=ctx.app.cache.get_role(record.get("role_id")),
                    label=record.get("buttonlabel"),
                    style=button_styles[record.get("buttonstyle")],
                    emoji=emoji,
                )
            )
        view = PersistentRoleView(buttons)
        components = view.build() if len(buttons) > 0 else []
        message = await message.edit(components=components)
        view.start(message)


@rolebutton.child()
@lightbulb.option(
    "buttonstyle",
    "The style of the button. Options: Blurple, Grey, Red, Green",
    required=False,
)
@lightbulb.option("label", "The label that should appear on the button.", required=False)
@lightbulb.option("emoji", "The emoji that should appear in the button.", type=hikari.Emoji)
@lightbulb.option("role", "The role that should be handed out by the button.", type=hikari.Role)
@lightbulb.option(
    "message_id",
    "The ID of a message that MUST be from the bot, the rolebutton will be attached here.",
)
@lightbulb.option(
    "channel",
    "The channel where the message is located in.",
    type=hikari.TextableGuildChannel,
    channel_types=[hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS],
)
@lightbulb.command(
    "add",
    "Add a new rolebutton. For new users, it is recommended to use /rolebutton setup instead.",
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_add(ctx: SnedSlashContext) -> None:
    style = ctx.options.buttonstyle or "Grey"

    if style.capitalize() not in button_styles.keys():
        embed = hikari.Embed(
            title="❌ Invalid button style",
            description=f"Button style must be one of the following: `{', '.join(button_styles.keys())}`.",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    if ctx.options.role.name == "@everyone" or ctx.options.role.is_managed:
        embed = hikari.Embed(
            title="❌ Invalid role",
            description="The specified role cannot be manually assigned.",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    try:
        message_id = int(ctx.options.message_id)
    except (TypeError, AssertionError):
        embed = hikari.Embed(
            title="❌ Invalid ID",
            description="Please enter a valid integer for parameter `message_id`",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    print(ctx.options.channel)

    try:
        message = await ctx.app.rest.fetch_message(ctx.options.channel.id, message_id)
    except (hikari.NotFoundError, hikari.ForbiddenError):
        embed = hikari.Embed(
            title="❌ Unknown message",
            description="Could not find message with this ID. Ensure the ID is valid, and that the bot has permissions to view the channel.",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    records = await ctx.app.pool.fetch("""SELECT entry_id FROM button_roles ORDER BY entry_id DESC LIMIT 1""")
    entry_id = records[0].get("entry_id") + 1 if records else 1

    button = RoleButton(
        entry_id=entry_id,
        role=ctx.options.role,
        emoji=hikari.Emoji.parse(ctx.options.emoji),
        label=ctx.options.label,
        style=button_styles[style.capitalize() or "Grey"],
    )

    buttons = []

    records = await ctx.app.db_cache.get(table="button_roles", guild_id=ctx.guild_id, msg_id=message_id)
    if records:
        # Account for other rolebuttons on the same message
        for record in records:
            emoji = hikari.Emoji.parse(record.get("emoji"))
            role = ctx.app.cache.get_role(record.get("role_id"))
            if not role:
                continue
            buttons.append(
                RoleButton(
                    entry_id=record.get("entry_id"),
                    role=role,
                    label=record.get("buttonlabel"),
                    style=button_styles[record.get("buttonstyle") or "Grey"],
                    emoji=emoji,
                )
            )

    buttons.append(button)
    view = PersistentRoleView(ctx.app, buttons=buttons)
    message = await message.edit(components=view.build())
    view.start(message)

    await ctx.app.pool.execute(
        """
        INSERT INTO button_roles (entry_id, guild_id, channel_id, msg_id, emoji, buttonlabel, buttonstyle, role_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        entry_id,
        ctx.guild_id,
        ctx.options.channel.id,
        message_id,
        str(ctx.options.emoji),
        ctx.options.label,
        ctx.options.buttonstyle,
        ctx.options.role.id,
    )
    await ctx.app.db_cache.refresh(table="button_roles", guild_id=ctx.guild_id)

    embed = hikari.Embed(
        title="✅ Done!",
        description=f"A new rolebutton for role {ctx.options.role.mention} in channel {ctx.options.channel.name} has been created!",
        color=ctx.app.embed_green,
    )
    await ctx.respond(embed=embed)


def load(bot: SnedBot) -> None:
    bot.add_plugin(role_buttons)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(role_buttons)
