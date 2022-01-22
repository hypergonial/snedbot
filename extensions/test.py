import logging

import hikari
from hikari.impl.bot import GatewayBot
import lightbulb
import miru

logger = logging.getLogger(__name__)

test = lightbulb.Plugin("Test")


class Confirm(miru.View):
    def __init__(self, bot: hikari.GatewayBot) -> None:
        super().__init__(bot, timeout=30)

        self.result: bool | None = None

    @miru.button(label="Confirm", style=hikari.ButtonStyle.SUCCESS, row=0)
    async def confirm(self, btn: miru.Button, ctx: miru.Interaction) -> None:
        self.result = True
        await ctx.send_message(f"self is: {self.name}")

    @miru.button(label="Cancel", style=hikari.ButtonStyle.DANGER, row=1)
    async def cancel(self, btn: miru.Button, ctx: miru.Interaction) -> None:
        self.result = False
        await ctx.send_message(f"self is: {self.name}")


@test.command()
@lightbulb.command("test", "AAAAAAAAAAA")
@lightbulb.implements(lightbulb.SlashCommand)
async def do_thing(ctx):
    view1 = Confirm(ctx.app)
    view1.name = "view1"
    view2 = Confirm(ctx.app)
    view2.name = "view2"
    for item in view1.children:
        print(item._rendered_row)
    print("------------")
    for item in view2.children:
        print(item._rendered_row)
    proxy1 = await ctx.respond("View 1", components=view1.build())
    proxy2 = await ctx.respond("View 2", components=view2.build())
    view1.start(await proxy1.message())
    view2.start(await proxy2.message())


def load(bot):
    logging.info("Adding plugin: Test")
    bot.add_plugin(test)


def unload(bot):
    logging.info("Removing plugin: Test")
    bot.remove_plugin(test)
