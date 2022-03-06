import datetime
import json
import logging
import typing as t

import hikari
import lightbulb
import miru

from etc import constants as const
from models import SnedBot, SnedSlashContext, Timer, events
from models.views import AuthorOnlyNavigator
from utils import helpers

reminders = lightbulb.Plugin(name="Reminders")

logger = logging.getLogger(__name__)


class ReminderView(miru.View):
    def __init__(self, timer_id: int, *args, **kwargs) -> None:
        self.timer_id = timer_id
        super().__init__(*args, **kwargs)

    async def on_timeout(self) -> None:
        for item in self.children:
            assert isinstance(item, miru.Button)
            item.disabled = True

        assert self.message is not None
        await self.message.edit(components=self.build())

    @miru.button(label="Remind me too!", emoji="✉️", style=hikari.ButtonStyle.PRIMARY)
    async def add_recipient(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        assert isinstance(self.app, SnedBot)
        assert ctx.guild_id is not None

        try:
            timer: Timer = await self.app.scheduler.get_timer(self.timer_id, ctx.guild_id)
        except ValueError:
            embed = hikari.Embed(
                title="❌ Invalid interaction",
                description="Oops! It looks like this reminder is no longer valid!",
                color=const.ERROR_COLOR,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        if timer.user_id == ctx.user.id:
            embed = hikari.Embed(
                title="❌ Invalid interaction",
                description="You cannot do this on your own reminder.",
                color=const.ERROR_COLOR,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

        assert timer.notes is not None
        notes: t.Dict[str, t.Any] = json.loads(timer.notes)

        if ctx.user.id not in notes["additional_recipients"]:

            if len(notes["additional_recipients"]) > 50:
                embed = hikari.Embed(
                    title="❌ Invalid interaction",
                    description="Oops! Looks like too many people signed up for this reminder. Try creating a new reminder! (Max cap: 50)",
                    color=const.ERROR_COLOR,
                )
                return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

            notes["additional_recipients"].append(ctx.user.id)
            timer.notes = json.dumps(notes)
            await self.app.scheduler.update_timer(timer)
            embed = hikari.Embed(
                title="✅ Signed up to reminder",
                description="You will be notified when this reminder is due!",
                color=const.EMBED_GREEN,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        else:
            notes["additional_recipients"].remove(ctx.user.id)
            timer.notes = json.dumps(notes)
            await self.app.scheduler.update_timer(timer)
            embed = hikari.Embed(
                title="✅ Removed from reminder",
                description="Removed you from the list of recipients!",
                color=const.EMBED_GREEN,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@reminders.command()
@lightbulb.command("reminder", "Manage reminders!")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def reminder(ctx: SnedSlashContext) -> None:
    pass


@reminder.child()  # type: ignore
@lightbulb.option("message", "The message that should be sent to you when this reminder expires.", str)
@lightbulb.option(
    "when", "When this reminder should expire. Examples: 'in 10 minutes', 'tomorrow at 20:00', '2022-04-01'", str
)
@lightbulb.command("create", "Create a new reminder.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_create(ctx: SnedSlashContext) -> None:

    assert ctx.guild_id is not None

    if len(ctx.options.message) >= 1000:
        embed = hikari.Embed(
            title="❌ Reminder too long",
            description="Your reminder cannot exceed **1000** characters!",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    try:
        time = await ctx.app.scheduler.convert_time(ctx.options.when, user=ctx.user, future_time=True)

    except ValueError as error:
        embed = hikari.Embed(
            title="❌ Error: Invalid data entered",
            description=f"Your timeformat is invalid! \n**Error:** {error}",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    if (time - helpers.utcnow()).total_seconds() >= 31536000 * 5:
        embed = hikari.Embed(
            title="❌ Error: Invalid data entered",
            description="Sorry, but that's a bit too far in the future.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    if (time - helpers.utcnow()).total_seconds() < 10:
        embed = hikari.Embed(
            title="❌ Error: Invalid data entered",
            description="Sorry, but that's a bit too short, reminders must last longer than `10` seconds.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    embed = hikari.Embed(
        title="✅ Reminder set",
        description=f"Reminder set for: {helpers.format_dt(time)} ({helpers.format_dt(time, style='R')})\n\n**Message:**\n{ctx.options.message}",
        color=const.EMBED_GREEN,
    )

    reminder_data = {
        "message": ctx.options.message,
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
    view = ReminderView(timer.id, timeout=300)
    proxy = await ctx.respond(embed=embed, components=view.build())

    reminder_data["jump_url"] = (await proxy.message()).make_link(ctx.guild_id)
    timer.notes = json.dumps(reminder_data)

    await ctx.app.scheduler.update_timer(timer)
    view.start(await proxy.message())


@reminder.child()  # type: ignore
@lightbulb.option("id", "The ID of the timer to delete. You can get this via /reminder list", type=int)
@lightbulb.command("delete", "Delete a currently pending reminder.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_del(ctx: SnedSlashContext) -> None:

    assert ctx.guild_id is not None

    try:
        await ctx.app.scheduler.cancel_timer(ctx.options.id, ctx.guild_id)
    except ValueError:
        embed = hikari.Embed(
            title="❌ Reminder not found",
            description=f"Cannot find reminder with ID **{ctx.options.id}**.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    embed = hikari.Embed(
        title="✅ Reminder deleted",
        description=f"Reminder **{ctx.options.id}** has been deleted.",
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

    if records:
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

    else:
        embed = hikari.Embed(
            title="✉️ No pending reminders!",
            description="You have no pending reminders. You can create one via `/reminder create`!",
            color=const.WARN_COLOR,
        )
        await ctx.respond(embed=embed)


@reminders.listener(events.TimerCompleteEvent, bind=True)
async def on_reminder(plugin: lightbulb.Plugin, event: events.TimerCompleteEvent):
    """
    Listener for expired reminders
    """
    if event.timer.event == "reminder":
        guild = plugin.app.cache.get_guild(event.timer.guild_id)
        assert guild is not None
        assert event.timer.channel_id is not None

        user = guild.get_member(event.timer.user_id)

        if not user:
            return

        if not guild:
            return

        assert event.timer.notes is not None
        notes = json.loads(event.timer.notes)
        embed = hikari.Embed(
            title=f"✉️ {user.display_name}, your reminder:",
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
                user_mentions=True,
            )

        except (
            hikari.ForbiddenError,
            hikari.NotFoundError,
            hikari.InternalServerError,
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
