import logging
import asyncpg

import hikari
import lightbulb
import miru
from models import SnedBot
import models
from models import SnedSlashContext
from utils import helpers
import typing as t

from utils.ratelimiter import BucketType, RateLimiter

logger = logging.getLogger(__name__)

# Set to true to migrate old stateful rolebuttons
MIGRATE = False

role_buttons = lightbulb.Plugin("Role-Buttons")

button_styles = {
    "Blurple": hikari.ButtonStyle.PRIMARY,
    "Grey": hikari.ButtonStyle.SECONDARY,
    "Green": hikari.ButtonStyle.SUCCESS,
    "Red": hikari.ButtonStyle.DANGER,
}
role_button_ratelimiter = RateLimiter(2, 1, BucketType.MEMBER, wait=False)


class PersistentRoleView(miru.View):
    def __init__(self, buttons: t.List[miru.Button]) -> None:
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
        label: t.Optional[str] = None,
        role: hikari.SnowflakeishOr[hikari.Role],
    ):
        role_id = hikari.Snowflake(role)
        super().__init__(style=style, label=label, emoji=emoji, custom_id=f"RB:{entry_id}:{role_id}")


@role_buttons.listener(lightbulb.LightbulbStartedEvent, bind=True)
async def migrate_rolebuttons(plugin: lightbulb.Plugin, event: lightbulb.LightbulbStartedEvent) -> None:
    if not MIGRATE:
        return

    records: asyncpg.Record = await plugin.app.pool.fetch("""SELECT * FROM button_roles""")

    msg_button_mapping: t.Dict[str, t.List[RoleButton]] = {}

    for record in records:
        button = RoleButton(
            entry_id=record.get("entry_id"),
            role=record.get("role_id"),
            label=record.get("buttonlabel"),
            style=button_styles[record.get("buttonstyle")],
            emoji=hikari.Emoji.parse(record.get("emoji")),
        )

        if f"{record.get('channel_id')}:{record.get('msg_id')}" not in msg_button_mapping:
            msg_button_mapping[f"{record.get('channel_id')}:{record.get('msg_id')}"] = [button]
        else:
            msg_button_mapping[f"{record.get('channel_id')}:{record.get('msg_id')}"].append(button)

    count = 0
    for compound_id, buttons in msg_button_mapping.items():
        channel_id = int(compound_id.split(":")[0])
        msg_id = int(compound_id.split(":")[1])

        view = PersistentRoleView(buttons)
        await plugin.app.rest.edit_message(channel_id, msg_id, components=view.build())
        count += 1
    logger.info(f"Migrated {count} role-buttons to stateless handling.")


@role_buttons.listener(miru.ComponentInteractionCreateEvent, bind=True)
async def rolebutton_listener(plugin: lightbulb.Plugin, event: miru.ComponentInteractionCreateEvent) -> None:
    """Statelessly listen for rolebutton interactions"""

    if not event.interaction.custom_id.startswith("RB:"):
        return

    entry_id = event.interaction.custom_id.split(":")[1]
    role_id = event.interaction.custom_id.split(":")[2]

    if not event.context.guild_id:
        return

    role = plugin.app.cache.get_role(role_id)

    if not role:
        embed = hikari.Embed(
            title="❌ Orphaned",
            description="The role this button was pointing to was deleted! Please notify an administrator!",
            color=0xFF0000,
        )
        return await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    me = plugin.app.cache.get_member(event.context.guild_id, plugin.app.user_id)
    if not helpers.includes_permissions(lightbulb.utils.permissions_for(me), hikari.Permissions.MANAGE_ROLES):
        embed = hikari.Embed(
            title="❌ Missing Permissions",
            description="Bot does not have `Manage Roles` permissions! Contact an administrator!",
            color=0xFF0000,
        )
        return await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    await role_button_ratelimiter.acquire(event.context)
    if role_button_ratelimiter.is_rate_limited(event.context):
        embed = hikari.Embed(
            title="❌ Slow Down!",
            description="You are clicking too fast!",
            color=0xFF0000,
        )
        return await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    await event.interaction.create_initial_response(
        hikari.ResponseType.DEFERRED_MESSAGE_CREATE, flags=hikari.MessageFlag.EPHEMERAL
    )

    try:
        if role.id in event.context.member.role_ids:
            await event.context.member.remove_role(role, reason=f"Removed by role-button (ID: {entry_id})")
            embed = hikari.Embed(
                title="✅ Role removed",
                description=f"Removed role: {role.mention}",
                color=0x77B255,
            )
            await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        else:
            await event.context.member.add_role(role, reason=f"Granted by role-button (ID: {entry_id})")
            embed = hikari.Embed(
                title="✅ Role added",
                description=f"Added role: {role.mention}",
                color=0x77B255,
            )
            embed.set_footer(text="If you would like it removed, click the button again!")
            await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    except (hikari.ForbiddenError, hikari.HTTPError):
        embed = hikari.Embed(
            title="❌ Insufficient permissions",
            description="Failed adding role due to an issue with permissions and/or role hierarchy! Please contact an administrator!",
            color=0xFF0000,
        )
        await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


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
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

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
    type=int,
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
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    await ctx.app.pool.execute(
        """DELETE FROM button_roles WHERE guild_id = $1 AND entry_id = $2""",
        ctx.guild_id,
        ctx.options.button_id,
    )
    await ctx.app.db_cache.refresh(table="button_roles", guild_id=ctx.guild_id)

    embed = hikari.Embed(
        title="✅ Deleted!",
        description=f"Rolebutton was successfully deleted!",
        color=ctx.app.embed_green,
    )
    await ctx.respond(embed=embed)

    try:
        message = await ctx.app.rest.fetch_message(records[0]["channel_id"], records[0]["msg_id"])
    except hikari.NotFoundError:
        pass
    else:
        records = await ctx.app.db_cache.get(table="button_roles", guild_id=ctx.guild_id, msg_id=message.id) or []
        buttons = []
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


@rolebutton.child()
@lightbulb.option("buttonstyle", "The style of the button.", choices=["Blurple", "Grey", "Red", "Green"])
@lightbulb.option("label", "The label that should appear on the button.", required=False)
@lightbulb.option("emoji", "The emoji that should appear in the button.", type=hikari.Emoji)
@lightbulb.option("role", "The role that should be handed out by the button.", type=hikari.Role)
@lightbulb.option(
    "message_link",
    "The link of a message that MUST be from the bot, the rolebutton will be attached here.",
)
@lightbulb.command(
    "add",
    "Add a new rolebutton.",
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def rolebutton_add(ctx: SnedSlashContext) -> None:

    ctx.options.buttonstyle = ctx.options.buttonstyle or "Grey"

    message = await helpers.parse_message_link(ctx, ctx.options.message_link)
    if not message:
        return

    records = await ctx.app.pool.fetch("""SELECT entry_id FROM button_roles ORDER BY entry_id DESC LIMIT 1""")
    entry_id = records[0].get("entry_id") + 1 if records else 1
    emoji = hikari.Emoji.parse(ctx.options.emoji) if ctx.options.emoji else None
    button_style = button_styles[ctx.options.buttonstyle.capitalize()]

    button = RoleButton(
        entry_id=entry_id,
        role=ctx.options.role,
        emoji=emoji,
        label=ctx.options.label,
        style=button_style,
    )

    buttons = []

    records = await ctx.app.db_cache.get(table="button_roles", guild_id=ctx.guild_id, msg_id=message.id)
    if records:
        # Account for other rolebuttons on the same message
        for record in records:
            old_emoji = hikari.Emoji.parse(record.get("emoji"))
            role = ctx.app.cache.get_role(record.get("role_id"))
            if not role:
                continue
            buttons.append(
                RoleButton(
                    entry_id=record.get("entry_id"),
                    role=role,
                    label=record.get("buttonlabel"),
                    style=button_styles[record.get("buttonstyle") or "Grey"],
                    emoji=old_emoji,
                )
            )

    buttons.append(button)
    view = PersistentRoleView(buttons=buttons)
    message = await message.edit(components=view.build())

    await ctx.app.pool.execute(
        """
        INSERT INTO button_roles (entry_id, guild_id, channel_id, msg_id, emoji, buttonlabel, buttonstyle, role_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
        entry_id,
        ctx.guild_id,
        message.channel_id,
        message.id,
        str(emoji),
        ctx.options.label,
        ctx.options.buttonstyle,
        ctx.options.role.id,
    )
    await ctx.app.db_cache.refresh(table="button_roles", guild_id=ctx.guild_id)

    channel = ctx.app.cache.get_guild_channel(message.channel_id)

    embed = hikari.Embed(
        title="✅ Done!",
        description=f"A new rolebutton for role {ctx.options.role.mention} in channel `#{channel.name}` has been created!",
        color=ctx.app.embed_green,
    )
    await ctx.respond(embed=embed)

    embed = hikari.Embed(
        title="❇️ Role-Button was added",
        description=f"A role-button for role {ctx.options.role.mention} has been created by {ctx.author.mention} in channel <#{channel.id}>.\n\n__Note:__ Anyone who can see this channel can now obtain this role!",
        color=ctx.app.embed_green,
    )
    try:
        await ctx.app.get_plugin("Logging").d.actions.log("roles", embed, ctx.guild.id)
    except AttributeError:
        pass


def load(bot: SnedBot) -> None:
    bot.add_plugin(role_buttons)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(role_buttons)
