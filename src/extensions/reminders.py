import datetime
import json
import logging
import typing as t

import arc
import hikari
import miru

from src.etc import const
from src.models.client import SnedClient, SnedContext, SnedPlugin
from src.models.events import TimerCompleteEvent  # noqa: TC001
from src.models.timer import TimerEvent
from src.models.views import AuthorOnlyNavigator
from src.utils import helpers

if t.TYPE_CHECKING:
    from miru.ext import nav

    from src.models import Timer

plugin = SnedPlugin(name="Reminders")

logger = logging.getLogger(__name__)


class SnoozeSelect(miru.TextSelect):
    def __init__(self) -> None:
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
        )

    @plugin.inject_dependencies
    async def callback(self, ctx: miru.ViewContext, client: SnedClient = miru.inject()) -> None:
        assert isinstance(self.view, SnoozeView)

        expiry = helpers.utcnow() + datetime.timedelta(minutes=int(self.values[0]))
        assert self.view.reminder_message.embeds[0].description and ctx.guild_id and isinstance(self.view, SnoozeView)
        message = self.view.reminder_message.embeds[0].description.split("\n\n[Jump to original message!](")[0]

        reminder_data: dict[str, t.Any] = {
            "message": message,
            "jump_url": ctx.message.make_link(ctx.guild_id),
            "additional_recipients": [],
            "is_snoozed": True,
        }

        timer = await client.scheduler.create_timer(
            expiry,
            TimerEvent.REMINDER,
            ctx.guild_id,
            ctx.user,
            ctx.channel_id,
            notes=json.dumps(reminder_data),
        )

        await ctx.edit_response(
            embed=hikari.Embed(
                title="✅ Reminder snoozed",
                description=f"Reminder snoozed until: {helpers.format_dt(expiry)} ({helpers.format_dt(expiry, style='R')})\n\n**Message:**\n{message}",
                color=const.EMBED_GREEN,
            ).set_footer(f"Reminder ID: {timer.id}"),
            components=miru.View().add_item(
                miru.TextSelect(placeholder="Reminder snoozed!", options=[miru.SelectOption("amongus")], disabled=True)
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        self.view.stop()


class SnoozeView(miru.View):
    def __init__(
        self, reminder_message: hikari.Message, *, timeout: float | None = 600, autodefer: bool = True
    ) -> None:
        super().__init__(timeout=timeout, autodefer=autodefer)
        self.reminder_message = reminder_message
        self.add_item(SnoozeSelect())

    async def on_timeout(self) -> None:
        return await super().on_timeout()


@plugin.listen()
@plugin.inject_dependencies
async def reminder_component_handler(
    event: hikari.InteractionCreateEvent, miru_client: miru.Client = arc.inject()
) -> None:
    inter = event.interaction

    if not isinstance(inter, hikari.ComponentInteraction) or inter.guild_id is None:
        return

    if not inter.custom_id.startswith(("RMSS:", "RMAR:")):
        return

    if inter.custom_id.startswith("RMSS:"):  # Snoozes
        author_id = hikari.Snowflake(inter.custom_id.split(":")[1])

        if author_id != inter.user.id:
            await inter.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                embed=hikari.Embed(
                    title="❌ Invalid interaction",
                    description="You cannot snooze someone else's reminder!",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        if not inter.message.embeds:
            return

        view = miru.View.from_message(inter.message)
        view.children[0].disabled = True
        await inter.create_initial_response(hikari.ResponseType.MESSAGE_UPDATE, components=view)

        view = SnoozeView(inter.message)
        msg = await inter.execute(
            embed=hikari.Embed(
                title="🕔 Select a snooze duration!",
                description="Select a duration to snooze the reminder for!",
                color=const.EMBED_BLUE,
            ),
            components=view,
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        miru_client.start_view(view, bind_to=msg)

    else:  # Reminder additional recipients
        timer_id = int(inter.custom_id.split(":")[1])
        try:
            timer: Timer = await plugin.client.scheduler.get_timer(timer_id, inter.guild_id)
            if timer.channel_id != inter.channel_id or timer.event != TimerEvent.REMINDER:
                raise ValueError

        except ValueError:
            await inter.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                embed=hikari.Embed(
                    title="❌ Invalid interaction",
                    description="Oops! It looks like this reminder is no longer valid!",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            view = miru.View.from_message(inter.message)

            for item in view.children:
                item.disabled = True
            await inter.message.edit(components=view)
            return

        if timer.user_id == inter.user.id:
            await inter.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                embed=hikari.Embed(
                    title="❌ Invalid interaction",
                    description="You cannot do this on your own reminder.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        assert timer.notes is not None
        notes: dict[str, t.Any] = json.loads(timer.notes)

        if inter.user.id not in notes["additional_recipients"]:
            if len(notes["additional_recipients"]) > 50:
                await inter.create_initial_response(
                    hikari.ResponseType.MESSAGE_CREATE,
                    embed=hikari.Embed(
                        title="❌ Invalid interaction",
                        description="Oops! Looks like too many people signed up for this reminder. Try creating a new reminder! (Max cap: 50)",
                        color=const.ERROR_COLOR,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return

            notes["additional_recipients"].append(inter.user.id)
            timer.notes = json.dumps(notes)
            await plugin.client.scheduler.update_timer(timer)
            await inter.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                embed=hikari.Embed(
                    title="✅ Signed up to reminder",
                    description="You will be notified when this reminder is due!",
                    color=const.EMBED_GREEN,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )

        else:
            notes["additional_recipients"].remove(inter.user.id)
            timer.notes = json.dumps(notes)
            await plugin.client.scheduler.update_timer(timer)
            await inter.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                embed=hikari.Embed(
                    title="✅ Removed from reminder",
                    description="Removed you from the list of recipients!",
                    color=const.EMBED_GREEN,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )


reminder = plugin.include_slash_group("reminder", "Manage reminders!")


@reminder.include
@arc.slash_subcommand("create", "Create a new reminder.")
async def reminder_create(
    ctx: SnedContext,
    when: arc.Option[
        str,
        arc.StrParams("When this reminder should expire. Examples: 'in 10 minutes', 'tomorrow at 20:00', '2022-04-01'"),
    ],
    message: arc.Option[
        str | None, arc.StrParams("The message that should be sent to you when this reminder expires.")
    ] = None,
) -> None:
    assert ctx.guild_id is not None

    if message and len(message) >= 1000:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Reminder too long",
                description="Your reminder cannot exceed **1000** characters!",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    try:
        time = await ctx.client.scheduler.convert_time(when, user=ctx.user, future_time=True)

    except ValueError as error:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid data entered",
                description=f"Your timeformat is invalid! \n**Error:** {error}",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if (time - helpers.utcnow()).total_seconds() >= 31536000 * 5:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid data entered",
                description="Sorry, but that's a bit too far in the future.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if (time - helpers.utcnow()).total_seconds() < 10:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid data entered",
                description="Sorry, but that's a bit too short, reminders must last longer than `10` seconds.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    reminder_data: dict[str, t.Any] = {
        "message": message,
        "jump_url": None,
        "additional_recipients": [],
    }

    timer = await ctx.client.scheduler.create_timer(
        expires=time,
        event=TimerEvent.REMINDER,
        guild=ctx.guild_id,
        user=ctx.author,
        channel=ctx.channel_id,
        notes=json.dumps(reminder_data),
    )

    resp = await ctx.respond(
        embed=hikari.Embed(
            title="✅ Reminder set",
            description=f"Reminder set for: {helpers.format_dt(time)} ({helpers.format_dt(time, style='R')})\n\n**Message:**\n{message}",
            color=const.EMBED_GREEN,
        ).set_footer(f"Reminder ID: {timer.id}  •  If this looks wrong, please set your timezone using /timezone"),
        components=miru.View().add_item(miru.Button(label="Remind me too!", emoji="✉️", custom_id=f"RMAR:{timer.id}")),
    )
    reminder_data["jump_url"] = (await resp.retrieve_message()).make_link(ctx.guild_id)
    timer.notes = json.dumps(reminder_data)

    await ctx.client.scheduler.update_timer(timer)


@reminder.include
@arc.slash_subcommand("delete", "Delete a currently pending reminder.")
async def reminder_del(
    ctx: SnedContext,
    id: arc.Option[int, arc.IntParams("The ID of the timer to delete. You can get this via /reminder list")],
) -> None:
    assert ctx.guild_id is not None

    try:
        await ctx.client.scheduler.cancel_timer(id, ctx.guild_id, ctx.author.id)
    except ValueError:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Reminder not found",
                description=f"Cannot find reminder with ID **{id}**.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.respond(
        embed=hikari.Embed(
            title="✅ Reminder deleted",
            description=f"Reminder **{id}** has been deleted.",
            color=const.EMBED_GREEN,
        )
    )


@reminder.include
@arc.slash_subcommand("list", "List your currently pending reminders.")
async def reminder_list(ctx: SnedContext) -> None:
    records = await ctx.client.db.fetch(
        """SELECT * FROM timers WHERE guild_id = $1 AND user_id = $2 AND event = 'reminder' ORDER BY expires""",
        ctx.guild_id,
        ctx.author.id,
    )

    if not records:
        await ctx.respond(
            embed=hikari.Embed(
                title="✉️ No pending reminders!",
                description="You have no pending reminders. You can create one via `/reminder create`!",
                color=const.WARN_COLOR,
            )
        )
        return

    reminders: list[str] = []

    for record in records:
        time = datetime.datetime.fromtimestamp(record["expires"])
        notes = json.loads(record["notes"])["message"].replace("\n", " ")
        if len(notes) > 50:
            notes = notes[:47] + "..."

        reminders.append(
            f"**ID: {record.get('id')}** - {helpers.format_dt(time)} ({helpers.format_dt(time, style='R')})\n{notes}\n"
        )

    reminders_pages = [reminders[i * 10 : (i + 1) * 10] for i in range((len(reminders) + 10 - 1) // 10)]

    pages: list[str | hikari.Embed | t.Sequence[hikari.Embed] | nav.Page] = [
        hikari.Embed(title="✉️ Your reminders:", description="\n".join(content), color=const.EMBED_BLUE)
        for content in reminders_pages
    ]

    navigator = AuthorOnlyNavigator(ctx.author, pages=pages, timeout=600)
    builder = await navigator.build_response_async(ctx.client.miru)
    await ctx.respond_with_builder(builder)


@plugin.listen()
async def on_reminder(event: TimerCompleteEvent):
    """Listener for expired reminders."""
    if event.timer.event != TimerEvent.REMINDER:
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

    to_ping = [user]

    if len(notes["additional_recipients"]) > 0:
        for user_id in notes["additional_recipients"]:
            member = guild.get_member(user_id)
            if member:
                to_ping.append(member)

    embed = hikari.Embed(
        title=f"✉️ {user.display_name}{f' and {len(to_ping) - 1} others' if len(to_ping) > 1 else ''}, your {'snoozed ' if notes.get('is_snoozed') else ''}reminder:",
        description=f"{notes['message']}\n\n[Jump to original message!]({notes['jump_url']})",
        color=const.EMBED_BLUE,
    )

    try:
        await plugin.client.rest.create_message(
            event.timer.channel_id,
            content=" ".join([user.mention for user in to_ping]),
            embed=embed,
            components=miru.View().add_item(
                miru.Button(emoji="🕔", label="Snooze!", custom_id=f"RMSS:{event.timer.user_id}")
            ),
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


@arc.loader
def load(client: SnedClient) -> None:
    client.add_plugin(plugin)


@arc.unloader
def unload(client: SnedClient) -> None:
    client.remove_plugin(plugin)


# Copyright (C) 2022-present hypergonial

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
