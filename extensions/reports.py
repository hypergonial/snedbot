import asyncio
import logging

import hikari
import lightbulb
import miru
from miru.ext import nav
from models.bot import SnedBot
from utils import helpers
import typing as t

logger = logging.getLogger(__name__)

report = lightbulb.Plugin("Reports")


class ReportModal(miru.Modal):
    def __init__(self, member: hikari.Member, message: t.Optional[hikari.Message]) -> None:
        super().__init__(f"Reporting {member.username}", autodefer=False)
        self.add_item(
            miru.TextInput(
                label="Reason for the Report",
                placeholder="Please enter why you believe this user should be investigated...",
                max_length=1000,
                required=True,
            )
        )
        self.add_item(
            miru.TextInput(
                label="Additional Context",
                placeholder="If you have any additional information or proof (e.g. screenshots), please link them here.",
                max_length=1000,
            )
        )
        self.message = message  # Associated message if any
        self.member = member  # Reported member
        self.reason: str = None
        self.info: str = None

    async def callback(self, ctx: miru.ModalContext) -> None:
        if not ctx.values:
            return

        for item, value in ctx.values.items():
            if item.label == "Reason for the Report":
                self.reason = value
            elif item.label == "Additional Context":
                self.info = value


@report.command()
@lightbulb.option("user", "The user that is to be reported.", type=hikari.Member, required=True)
@lightbulb.command("report", "Report a user to the moderation team of this server.")
@lightbulb.implements(lightbulb.SlashCommand)
async def report(ctx: lightbulb.SlashContext) -> None:
    modal = ReportModal(member=ctx.options.user)
    await modal.send(ctx.interaction)


def load(bot: SnedBot) -> None:
    bot.add_plugin(report)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(report)
