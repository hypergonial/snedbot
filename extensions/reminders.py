import asyncio
import datetime
import json
import logging
from typing import Any, Dict

import hikari
import lightbulb
import miru
from objects.models import events
from objects.models.timer import Timer
from objects.utils import helpers

reminders = lightbulb.Plugin(name="Reminders")

logger = logging.getLogger(__name__)


class ReminderView(miru.View):
    def __init__(self, timer_id: int, *args, **kwargs) -> None:
        self.timer_id = timer_id
        super().__init__(*args, **kwargs)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

        await self.message.edit(components=self.build())

    @miru.button(label="Remind me too!", emoji="✉️", style=hikari.ButtonStyle.PRIMARY)
    async def add_recipient(self, button: miru.Button, interaction: miru.Interaction) -> None:
        await self.message.edit("Added more content")
        try:
            timer: Timer = await self.app.scheduler.get_timer(self.timer_id, interaction.guild_id)
        except ValueError:
            embed = hikari.Embed(
                title="❌ Invalid interaction",
                description="Oops! It looks like this reminder is no longer valid!",
                color=self.app.error_color,
            )
            await interaction.send_message(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        else:
            if timer.user_id == interaction.user.id:
                embed = hikari.Embed(
                    title="❌ Invalid interaction",
                    description="You cannot do this on your own reminder.",
                    color=self.app.error_color,
                )
                return await interaction.send_message(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

            notes: Dict[str, Any] = json.loads(timer.notes)

            if interaction.user.id not in notes["additional_recipients"]:

                if len(notes["additional_recipients"]) < 50:
                    notes["additional_recipients"].append(interaction.user.id)
                    await self.app.update_timer(
                        datetime.datetime.fromtimestamp(timer.expires, tz=datetime.timezone.utc),
                        self.timer_id,
                        interaction.guild_id,
                        new_notes=json.dumps(notes),
                    )
                    embed = hikari.Embed(
                        title="✅ Signed up to reminder",
                        description="You will also be notified when this reminder is due!",
                        color=self.app.embed_green,
                    )
                    return await interaction.send_message(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

                else:
                    embed = hikari.Embed(
                        title="❌ Invalid interaction",
                        description="Oops! Looks like too many people signed up for this reminder. Try creating a new reminder! (Max cap: 50)",
                        color=self.app.error_color,
                    )
                    return await interaction.send_message(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
            else:
                notes["additional_recipients"].remove(interaction.user.id)
                await self.app.update_timer(
                    datetime.datetime.fromtimestamp(timer.expires, tz=datetime.timezone.utc),
                    self.timer_id,
                    self.guild_id,
                    new_notes=json.dumps(notes),
                )
                embed = hikari.Embed(
                    title="✅ Removed from reminder",
                    description="Removed you from the list of recipients!",
                    color=self.app.embed_green,
                )
                return await interaction.send_message(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@reminders.command()
@lightbulb.command("reminder", "Manage reminders!")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def reminder(ctx: lightbulb.Context) -> None:
    pass


@lightbulb.option("message", "The message that should be sent to you when this reminder expires.", str)
@lightbulb.option("when", "When this reminder should expire.", str)
@reminder.child()
@lightbulb.command("create", "Create a new reminder.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_create(ctx: lightbulb.Context) -> None:
    if len(ctx.options.message) >= 1000:
        embed = hikari.Embed(
            title="❌ Reminder too long",
            description="Your reminder cannot exceed **1000** characters!",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed)

    try:
        time = await ctx.app.scheduler.convert_time(ctx.options.when)

    except ValueError as error:
        embed = hikari.Embed(
            title="❌ Error: Invalid data entered",
            description=f"Your timeformat is invalid! \n**Error:** {error}",
            color=ctx.app.error_color,
        )
        await ctx.respond(embed=embed)

    else:
        if (time - datetime.datetime.now(datetime.timezone.utc)).total_seconds() >= 31536000 * 5:
            embed = hikari.Embed(
                title="❌ Error: Invalid data entered",
                description="Sorry, but that's a bit too far in the future.",
                color=ctx.app.error_color,
            )
            await ctx.respond(embed=embed)

        else:

            embed = hikari.Embed(
                title="✅ Reminder set",
                description=f"Reminder set for:  {helpers.format_dt(time)} ({helpers.format_dt(time, style='R')})",
                color=ctx.app.embed_green,
            )
            embed = helpers.add_embed_footer(embed, ctx.member)

            reminder_data = {
                "message": ctx.options.message,
                "jump_url": None,
                "additional_recipients": [],
            }

            timer = await ctx.app.scheduler.create_timer(
                expires=time,
                event="reminder",
                guild_id=ctx.guild_id,
                user_id=ctx.author.id,
                channel_id=ctx.channel_id,
                notes=json.dumps(reminder_data),
            )

            view = ReminderView(timer.id, ctx.app, timeout=300)
            proxy = await ctx.respond(embed=embed, components=view.build())
            reminder_data["jump_url"] = (await proxy.message()).make_link(ctx.guild_id)
            await ctx.app.scheduler.update_timer(time, timer.id, timer.guild_id, new_notes=json.dumps(reminder_data))
            view.start(await proxy.message())


@reminder.child()
@lightbulb.command("delete", "Delete a currently pending reminder.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_del(ctx: lightbulb.Context) -> None:
    await ctx.respond("Test delete!")


@reminder.child()
@lightbulb.command("list", "List your currently pending reminders.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def reminder_list(ctx: lightbulb.Context) -> None:
    await ctx.respond("Test list!")


@reminders.listener(events.TimerCompleteEvent, bind=True)
async def on_reminder(plugin: lightbulb.Plugin, event: events.TimerCompleteEvent):
    """
    Listener for expired reminders
    """
    if event.timer.event == "reminder":
        guild = plugin.app.cache.get_guild(event.timer.guild_id)
        user = guild.get_member(event.timer.user_id)

        if user:
            notes = json.loads(event.timer.notes)
            embed = hikari.Embed(
                title=f"✉️ {user.display_name}, your reminder:",
                description=f"{notes['message']}\n\n[Jump to original message!]({notes['jump_url']})",
                color=plugin.app.embed_blue,
            )

            pings = [user.mention]

            if len(notes["additional_recipients"]) > 0:
                for user_id in notes["additional_recipients"]:
                    member = guild.get_member(user_id)
                    if member:
                        pings.append(member.mention)

            try:
                await plugin.app.rest.create_message(
                    event.timer.channel_id, content=" ".join(pings), embed=embed, user_mentions=True
                )

            except (hikari.ForbiddenError, hikari.NotFoundError, hikari.InternalServerError):
                try:
                    await user.send(
                        content="I lost access to the channel this reminder was sent from, so here it is!", embed=embed
                    )

                except hikari.ForbiddenError:
                    logger.info(f"Failed to deliver a reminder to user {user}.")


def load(bot):
    logger.info("Adding plugin: Reminders")
    bot.add_plugin(reminders)


def unload(bot):
    logger.info("Removing plugin: Reminders")
    bot.remove_plugin(reminders)
