import asyncio
import logging
import random

import hikari
import lightbulb
import miru
from hikari.impl.bot import GatewayBot

logger = logging.getLogger(__name__)

test = lightbulb.Plugin("Test")


class Confirm(miru.View):
    def __init__(self, bot: hikari.GatewayBot) -> None:
        super().__init__(bot)

    @miru.button(label="Reset", style=hikari.ButtonStyle.SUCCESS, row=0)
    async def confirm(self, btn: miru.Button, ctx: miru.Interaction) -> None:
        print("--- COMMENCE BULK-RESET ---")
        for item in self.children:
            if item != btn:
                item.row = 1
        # All items should now go back to row 1 right?
        # Wrong!
        # Now there are two items in row 0, and two in row 1
        print("--- BULK RESET END ---")

        await ctx.edit_message(components=self.build())

    @miru.button(label="Danger", style=hikari.ButtonStyle.DANGER, row=0)
    async def danger(self, btn: miru.Button, ctx: miru.Interaction) -> None:
        await ctx.send_message("You suck")

    @miru.button(label="Blurple", style=hikari.ButtonStyle.PRIMARY, row=0)
    async def blurple(self, btn: miru.Button, ctx: miru.Interaction) -> None:
        await ctx.send_message("You suck")

    @miru.button(label="Grey", style=hikari.ButtonStyle.SECONDARY, row=0)
    async def grey(self, btn: miru.Button, ctx: miru.Interaction) -> None:
        await ctx.send_message("You suck")


@test.command()
@lightbulb.command("test", "AAAAAAAAAAA")
@lightbulb.implements(lightbulb.SlashCommand)
async def do_thing(ctx):
    view1 = Confirm(ctx.app)
    view1.name = "view1"

    proxy1 = await ctx.respond("View 1", components=view1.build())
    view1.start(await proxy1.message())
    for item in view1.children:
        print(item)


def load(bot):
    logging.info("Adding plugin: Test")
    bot.add_plugin(test)


def unload(bot):
    logging.info("Removing plugin: Test")
    bot.remove_plugin(test)
