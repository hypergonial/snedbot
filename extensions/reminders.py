import datetime
import json
import logging
import typing as t

import hikari
import lightbulb
import miru

from etc import constants as const
from models import SnedBot
from models import SnedSlashContext
from models import Timer
from models import events
from models.views import AuthorOnlyNavigator
from utils import helpers

reminders = lightbulb.Plugin(name="Reminders")

logger = logging.getLogger(__name__)


class SnoozeSelect(miru.Select):
    def __init__(self, user: hikari.SnowflakeishOr[hikari.PartialUser]) -> None:
        super().__init__(
            options=[
                miru.SelectOption(label="5 minutes", value="5"),
                miru.SelectOption(label="15 minutes", value="15"),
                miru.SelectOption(label="30 minutes", value="30"),
                miru.SelectOption(label="1 hour", value="60"),
                miru.SelectOption(label="2 hours", value="120"),
                miru.SelectOption(label="3 hours", value="180"),
                miru.SelectOption(label="6 hours", value="360"),
                miru.SelectOption(label="12 hours", value="720"),
                miru.SelectOption(label="1 day", value="1440"),
            ],
            placeholder="Snooze reminder...",
            custom_id=f"RMSS:{hikari.Snowflake(user)}",
        )


@reminders.listener(miru.ComponentInteractionCreateEvent, bind=True)
async def reminder_component_handler(plugin: lightbulb.Plugin, event: miru.ComponentInteractionCreateEvent) -> None:

    if not event.interaction.custom_id.startswith(("RMSS:", "RMAR:")):
        return

    assert isinstance(plugin.app, SnedBot) and event.context.guild_id is not None

    if event.interaction.custom_id.startswith("RMSS:"):  # Snoozes
        author_id = hikari.Snowflake(event.interaction.custom_id.split(":")[1])

        if author_id != event.context.user.id:
            embed = hikari.Embed(
                title="❌ Invalid interaction",
                description="You cannot snooze someone else's reminder!",
                color=const.ERROR_COLOR,
            )
            return await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        if not event.interaction.message.embeds:
            return

        expiry = helpers.utcnow() + datetime.timedelta(minutes=int(event.interaction.values[0]))
        assert event.interaction.message.embeds[0].description is not None
        message = event.interaction.message.embeds[0].description.split("\n\n[Jump to original message!](")[0]

        reminder_data = {
            "message": message,
            "jump_url": event.interaction.message.make_link(event.context.guild_id),
            "additional_recipients": [],
            "is_snoozed": True,
        }

        timer = await plugin.app.scheduler.create_timer(
            expiry,
            "reminder",
            event.context.guild_id,
            event.context.user,
            event.context.channel_id,
            notes=json.dumps(reminder_data),
        )

        embed = hikari.Embed(
            title="✅ Reminder snoozed",
            description=f"Reminder snoozed until: {helpers.format_dt(expiry)} ({helpers.format_dt(expiry, style='R')})\n\n**Message:**\n{message}",
            color=const.EMBED_GREEN,
        )
        embed.set_footer(f"Reminder ID: {timer.id}")

        await event.context.edit_response(
            components=miru.View()
            .add_item(miru.Select(placeholder="Reminder snoozed!", options=[miru.SelectOption("foo")], disabled=True))
            .build()
        )
        await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    else:  # Reminder additional recipients
        timer_id = int(event.interaction.custom_id.split(":")[1])
        try:
            timer: Timer = await plugin.app.scheduler.get_timer(timer_id, event.context.guild_id)
            if timer.channel_id != event.context.channel_id or timer.event != "reminder":
                raise ValueError

        except ValueError:
            embed = hikari.Embed(
                title="❌ Invalid interaction",
                description="Oops! It looks like this reminder is no longer valid!",
                color=const.ERROR_COLOR,
            )
            return await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        if timer.user_id == event.context.user.id:
            embed = hikari.Embed(
                title="❌ Invalid interaction",
                description="You cannot do this on your own reminder.",
                color=const.ERROR_COLOR,
            )
            return await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        assert timer.notes is not None
        notes: t.Dict[str, t.Any] = json.loads(timer.notes)

        if event.context.user.id not in notes["additional_recipients"]:

            if len(notes["additional_recipients"]) > 50:
                embed = hikari.Embed(
                    title="❌ Invalid interaction",
                    description="Oops! Looks like too many people signed up for this reminder. Try creating a new reminder! (Max cap: 50)",
                    color=const.ERROR_COLOR,
                )
                return await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

            notes["additional_recipients"].append(event.context.user.id)
            timer.notes = json.dumps(notes)
            await plugin.app.scheduler.update_timer(timer)
            embed = hikari.Embed(
                title="✅ Signed up to reminder",
                description="You will be notified when this reminder is due!",
                color=const.EMBED_GREEN,
            )
            return await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        else:
            notes["additional_recipients"].remove(event.context.user.id)
            timer.notes = json.dumps(notes)
            await plugin.app.scheduler.update_timer(timer)
            embed = hikari.Embed(
                title="✅ Removed from reminder",
                description="Removed you from the list of recipients!",
                color=const.EMBED_GREEN,
            )
            return await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@reminders.command()
@lightbulb.command("reminder", "Manage reminders!")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def reminder(ctx: SnedSlashContext) -> None:
    pass


@reminder.child()  # type: ignore
@lightbulb.option("message", "The message that should be sent to you when this reminder expires.")
@lightbulb.option(
    "when", "When this reminder should expire. Examples: 'in 10 minutes', 'tomorrow at 20:00', '2022-04-01'"
)
@lightbulb.command("create", "Create a new reminder.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_create(ctx: SnedSlashContext, when: str, message: t.Optional[str] = None) -> None:

    assert ctx.guild_id is not None

    if message and len(message) >= 1000:
        embed = hikari.Embed(
            title="❌ Reminder too long",
            description="Your reminder cannot exceed **1000** characters!",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    try:
        time = await ctx.app.scheduler.convert_time(when, user=ctx.user, future_time=True)

    except ValueError as error:
        embed = hikari.Embed(
            title="❌ Invalid data entered",
            description=f"Your timeformat is invalid! \n**Error:** {error}",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    if (time - helpers.utcnow()).total_seconds() >= 31536000 * 5:
        embed = hikari.Embed(
            title="❌ Invalid data entered",
            description="Sorry, but that's a bit too far in the future.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    if (time - helpers.utcnow()).total_seconds() < 10:
        embed = hikari.Embed(
            title="❌ Invalid data entered",
            description="Sorry, but that's a bit too short, reminders must last longer than `10` seconds.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    embed = hikari.Embed(
        title="✅ Reminder set",
        description=f"Reminder set for: {helpers.format_dt(time)} ({helpers.format_dt(time, style='R')})\n\n**Message:**\n{message}",
        color=const.EMBED_GREEN,
    )

    reminder_data = {
        "message": message,
        "jump_url": None,
        "additional_recipients": [],
    }

    timer = await ctx.app.scheduler.create_timer(
        expires=time,
        event="reminder",
        guild=ctx.guild_id,
        user=ctx.author,
        channel=ctx.channel_id,
        notes=json.dumps(reminder_data),
    )

    embed.set_footer(f"Reminder ID: {timer.id}")
    proxy = await ctx.respond(
        embed=embed,
        components=miru.View()
        .add_item(miru.Button(label="Remind me too!", emoji="✉️", custom_id=f"RMAR:{timer.id}"))
        .build(),
    )

    reminder_data["jump_url"] = (await proxy.message()).make_link(ctx.guild_id)
    timer.notes = json.dumps(reminder_data)

    await ctx.app.scheduler.update_timer(timer)


@reminder.child()  # type: ignore
@lightbulb.option("id", "The ID of the timer to delete. You can get this via /reminder list", type=int)
@lightbulb.command("delete", "Delete a currently pending reminder.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_del(ctx: SnedSlashContext, id: int) -> None:

    assert ctx.guild_id is not None

    try:
        await ctx.app.scheduler.cancel_timer(id, ctx.guild_id)
    except ValueError:
        embed = hikari.Embed(
            title="❌ Reminder not found",
            description=f"Cannot find reminder with ID **{id}**.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    embed = hikari.Embed(
        title="✅ Reminder deleted",
        description=f"Reminder **{id}** has been deleted.",
        color=const.EMBED_GREEN,
    )
    await ctx.respond(embed=embed)


@reminder.child()  # type: ignore
@lightbulb.command("list", "List your currently pending reminders.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_list(ctx: SnedSlashContext) -> None:
    records = await ctx.app.pool.fetch(
        """SELECT * FROM timers WHERE guild_id = $1 AND user_id = $2 AND event = 'reminder' ORDER BY expires""",
        ctx.guild_id,
        ctx.author.id,
    )

    if not records:
        embed = hikari.Embed(
            title="✉️ No pending reminders!",
            description="You have no pending reminders. You can create one via `/reminder create`!",
            color=const.WARN_COLOR,
        )
        await ctx.respond(embed=embed)
        return

    reminders = []

    for record in records:
        time = datetime.datetime.fromtimestamp(record.get("expires"))
        notes = json.loads(record["notes"])["message"].replace("\n", " ")
        if len(notes) > 50:
            notes = notes[:47] + "..."

        reminders.append(
            f"**ID: {record.get('id')}** - {helpers.format_dt(time)} ({helpers.format_dt(time, style='R')})\n{notes}\n"
        )

    reminders = [reminders[i * 10 : (i + 1) * 10] for i in range((len(reminders) + 10 - 1) // 10)]

    pages = [
        hikari.Embed(title="✉️ Your reminders:", description="\n".join(content), color=const.EMBED_BLUE)
        for content in reminders
    ]
    # TODO: wtf
    navigator = AuthorOnlyNavigator(ctx, pages=pages)  # type: ignore
    await navigator.send(ctx.interaction)


@reminders.listener(events.TimerCompleteEvent, bind=True)
async def on_reminder(plugin: lightbulb.Plugin, event: events.TimerCompleteEvent):
    """
    Listener for expired reminders
    """
    if event.timer.event != "reminder":
        return

    guild = event.get_guild()

    if not guild:
        return

    assert event.timer.channel_id is not None

    user = guild.get_member(event.timer.user_id)

    if not user:
        return

    if not guild:
        return

    assert event.timer.notes is not None
    notes = json.loads(event.timer.notes)
    embed = hikari.Embed(
        title=f"✉️ {user.display_name}, your {'snoozed' if notes.get('is_snoozed') else ''} reminder:",
        description=f"{notes['message']}\n\n[Jump to original message!]({notes['jump_url']})",
        color=const.EMBED_BLUE,
    )

    pings = [user.mention]

    if len(notes["additional_recipients"]) > 0:
        for user_id in notes["additional_recipients"]:
            member = guild.get_member(user_id)
            if member:
                pings.append(member.mention)

    try:
        await plugin.app.rest.create_message(
            event.timer.channel_id,
            content=" ".join(pings),
            embed=embed,
            components=miru.View().add_item(SnoozeSelect(event.timer.user_id)).build(),
            user_mentions=True,
        )
    except (
        hikari.ForbiddenError,
        hikari.NotFoundError,
        hikari.HTTPError,
    ):
        try:
            await user.send(
                content="I lost access to the channel this reminder was sent from, so here it is!",
                embed=embed,
            )

        except hikari.ForbiddenError:
            logger.info(f"Failed to deliver a reminder to user {user}.")


def load(bot: SnedBot) -> None:
    bot.add_plugin(reminders)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(reminders)
