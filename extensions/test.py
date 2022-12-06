import asyncio
import logging

import hikari
import kosu
import lightbulb
import miru
from miru.ext import nav

from etc import const
from models import SnedSlashContext
from models.bot import SnedBot
from models.plugin import SnedPlugin
from utils import helpers

logger = logging.getLogger(__name__)

test = SnedPlugin("Test")


@test.listener(hikari.StartedEvent)
async def start_views(event: hikari.StartedEvent) -> None:
    await PersistentThing().start()


class PersistentThing(miru.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @miru.button(label="Foo!", style=hikari.ButtonStyle.SUCCESS, custom_id="foo")
    async def foo_button(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        await ctx.respond("You clicked foo!")

    @miru.button(label="Bar!", style=hikari.ButtonStyle.SUCCESS, custom_id="bar")
    async def bar_button(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        await ctx.respond("You clicked bar!")


class BasicView(miru.View):

    # Define a new Select menu with two options
    @miru.select(
        placeholder="Select me!",
        options=[
            miru.SelectOption(label="Option 1"),
            miru.SelectOption(label="Option 2"),
        ],
    )
    async def basic_select(self, select: miru.Select, ctx: miru.ViewContext) -> None:
        await ctx.respond(f"You've chosen {select.values[0]}!")

    # Define a new Button with the Style of success (Green)
    @miru.button(label="Click me!", style=hikari.ButtonStyle.SUCCESS)
    async def basic_button(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        await ctx.respond("You clicked me!")

    # Define a new Button that when pressed will stop the view & invalidate all the buttons in this view
    @miru.button(label="Modal!", style=hikari.ButtonStyle.PRIMARY)
    async def stop_button(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        modal = BasicModal()
        await ctx.respond_with_modal(modal)


class BasicModal(miru.Modal):
    def __init__(self) -> None:
        super().__init__("Miru is cool!")
        self.add_item(miru.TextInput(label="Enter something!", placeholder="Miru is cool!"))
        self.add_item(
            miru.TextInput(
                label="Enter something long!",
                style=hikari.TextInputStyle.PARAGRAPH,
                min_length=200,
                max_length=1000,
            )
        )

    async def callback(self, ctx: miru.ModalContext) -> None:
        await ctx.respond(self.values)


@test.command
@lightbulb.command("mirupersistent", "Test miru persistent unbound")
@lightbulb.implements(lightbulb.SlashCommand)
async def miru_persistent(ctx: SnedSlashContext) -> None:
    await ctx.respond("Beep Boop!", components=PersistentThing())


@test.listener(hikari.GuildMessageCreateEvent)
async def nonce_printer(event: hikari.GuildMessageCreateEvent) -> None:
    print(f"Nonce is: {event.message.nonce}")


@test.command
@lightbulb.command("mirutest", "Test miru views")
@lightbulb.implements(lightbulb.SlashCommand)
async def viewtest(ctx: SnedSlashContext) -> None:
    view = BasicView()
    view.add_item(miru.Button(label="Settings!", url="discord://-/settings/advanced"))
    resp = await ctx.respond("foo", components=view)
    await view.start(await resp.message())


@test.command
@lightbulb.command("modaltest", "Test miru modals")
@lightbulb.implements(lightbulb.SlashCommand)
async def modaltest(ctx: SnedSlashContext) -> None:
    modal = BasicModal()
    await modal.send(ctx.interaction)


@test.command
@lightbulb.command("navtest", "Test miru nav")
@lightbulb.implements(lightbulb.SlashCommand)
async def navtest(ctx: SnedSlashContext) -> None:

    buttons = [nav.FirstButton(), nav.PrevButton(), nav.StopButton(), nav.NextButton(), nav.LastButton()]

    navigator = nav.NavigatorView(pages=["1", "2", "3"], buttons=buttons)
    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    await navigator.send(ctx.interaction, responded=True)


@test.command
@lightbulb.option("text", "Text to analyze.")
@lightbulb.command("perspectivetestmultiple", "aaa", auto_defer=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def testmultiple_cmd(ctx: SnedSlashContext) -> None:
    text = ctx.options.text
    resps = []
    for i in range(1, 80):
        try:
            print(f"REQUEST {i}")

            resp: kosu.AnalysisResponse = await ctx.app.perspective.analyze(
                text, kosu.Attribute(kosu.AttributeName.TOXICITY)
            )
            resps.append(resp)
        except:
            raise

    resp_strs = []
    for resp in resps:
        score = resp.attribute_scores[0].summary
        resp_strs.append(f"{score.value}")
    await ctx.respond("\n".join(resp_strs))


@test.command
@lightbulb.option("text", "Text to analyze.")
@lightbulb.command("perspectivetest", "aaa", auto_defer=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def test_cmd(ctx: SnedSlashContext) -> None:
    text = ctx.options.text
    attribs = [
        kosu.Attribute(kosu.AttributeName.TOXICITY),
        kosu.Attribute(kosu.AttributeName.SEVERE_TOXICITY),
        kosu.Attribute(kosu.AttributeName.IDENTITY_ATTACK),
        kosu.Attribute(kosu.AttributeName.PROFANITY),
        kosu.Attribute(kosu.AttributeName.INSULT),
        kosu.Attribute(kosu.AttributeName.THREAT),
    ]
    assert ctx.app.perspective is not None
    resp: kosu.AnalysisResponse = await ctx.app.perspective.analyze(text, attribs)

    content = "```"
    for score in resp.attribute_scores:
        content = f"{content}\n{score.name}: {score.summary.score_type}: {score.summary.value}"
    content = f"{content}```"
    await ctx.respond(content=content)


def load(bot: SnedBot) -> None:
    # bot.add_plugin(test)
    pass


def unload(bot: SnedBot) -> None:
    # bot.remove_plugin(test)
    pass


# Copyright (C) 2022-present HyperGH

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
