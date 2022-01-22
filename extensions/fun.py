import logging
import random
from enum import IntEnum
from pathlib import Path
from typing import Optional

import aiohttp
import hikari
import lightbulb
import miru
from hikari.impl.bot import GatewayBot
from objects.utils import helpers

logger = logging.getLogger(__name__)

fun = lightbulb.Plugin("Fun")


class WinState(IntEnum):
    PLAYER_X = 0
    PLAYER_O = 1
    TIE = 2


class TicTacToeButton(miru.Button):
    def __init__(self, x: int, y: int) -> None:
        super().__init__(style=hikari.ButtonStyle.SECONDARY, label="\u200b", row=y)
        self.x: int = x
        self.y: int = y

    async def callback(self, interaction: miru.Interaction) -> None:
        if isinstance(self.view, TicTacToeView) and self.view.current_player.id == interaction.user.id:
            view: TicTacToeView = self.view
            value: int = view.board[self.y][self.x]

            if value in (view.size, -view.size):  # If already clicked
                return

            if view.current_player.id == view.playerx.id:
                self.style = hikari.ButtonStyle.DANGER
                self.label = "X"
                self.disabled = True
                view.board[self.y][self.x] = -1
                view.current_player = view.playero
                embed = hikari.Embed(
                    title="Tic Tac Toe!", description=f"It is **{view.playero.username}**'s turn!", color=0x009DFF
                )
                embed.set_thumbnail(helpers.get_display_avatar(view.playero))

            else:
                self.style = hikari.ButtonStyle.SUCCESS
                self.label = "O"
                self.disabled = True
                view.board[self.y][self.x] = 1
                view.current_player = view.playerx
                embed = hikari.Embed(
                    title="Tic Tac Toe!", description=f"It is **{view.playerx.username}**'s turn!", color=0x009DFF
                )
                embed.set_thumbnail(helpers.get_display_avatar(view.playerx))

            winner = view.check_winner()

            if winner is not None:

                if winner == WinState.PLAYER_X:
                    embed = hikari.Embed(
                        title="Tic Tac Toe!", description=f"**{view.playerx.username}** won!", color=0x77B255
                    )
                    embed.set_thumbnail(helpers.get_display_avatar(view.playerx))

                elif winner == WinState.PLAYER_O:
                    embed = hikari.Embed(
                        title="Tic Tac Toe!", description=f"**{view.playero.username}** won!", color=0x77B255
                    )
                    embed.set_thumbnail(helpers.get_display_avatar(view.playero))

                else:
                    embed = hikari.Embed(title="Tic Tac Toe!", description=f"It's a tie!", color=0x77B255)
                    embed.set_thumbnail(None)

                for button in view.children:
                    button.disabled = True

                view.stop()

            await interaction.edit_message(embed=embed, components=view.build())


class TicTacToeView(miru.View):
    def __init__(self, app: GatewayBot, size: int, playerx: hikari.Member, playero: hikari.Member) -> None:
        super().__init__(app)
        self.current_player: hikari.Member = playerx
        self.size: int = size
        self.playerx: hikari.Member = playerx
        self.playero: hikari.Member = playero

        if size in [3, 4, 5]:
            # Create board
            self.board = [[0 for _ in range(size)] for _ in range(size)]

        else:
            raise TypeError("Invalid size specified. Must be either 3, 4, 5.")

        for x in range(size):
            for y in range(size):
                self.add_item(TicTacToeButton(x, y))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

        embed = hikari.Embed(
            title="Tic Tac Toe!", description="This game timed out! Try starting a new one!", color=0xFF0000
        )
        await self.message.edit(embed=embed, components=self.build())

    def check_blocked(self) -> bool:
        """
        Check if the board is blocked
        """
        blocked_list = [False, False, False, False]

        # Check rows
        blocked = []
        for row in self.board:
            if not (-1 in row and 1 in row):
                blocked.append(False)
            else:
                blocked.append(True)

        if blocked.count(True) == len(blocked):
            blocked_list[0] = True

        # Check columns
        values = []
        for col in range(self.size):
            values.append([])
            for row in self.board:
                values[col].append(row[col])

        blocked = []
        for col in values:
            if not (-1 in col and 1 in col):
                blocked.append(False)
            else:
                blocked.append(True)
        if blocked.count(True) == len(blocked):
            blocked_list[1] = True

        # Check diagonals
        values = []
        diag_offset = self.size - 1
        for i in range(0, self.size):
            values.append(self.board[i][diag_offset])
            diag_offset -= 1
        if -1 in values and 1 in values:
            blocked_list[2] = True

        values = []
        diag_offset = 0
        for i in range(0, self.size):
            values.append(self.board[i][diag_offset])
            diag_offset += 1
        if -1 in values and 1 in values:
            blocked_list[3] = True

        if blocked_list.count(True) == len(blocked_list):
            return True

        return False

    def check_winner(self) -> Optional[WinState]:
        """
        Check if there is a winner
        """

        # Check rows
        for row in self.board:
            value = sum(row)
            if value == self.size:
                return WinState.PLAYER_O
            elif value == -self.size:
                return WinState.PLAYER_X

        # Check columns
        for col in range(self.size):
            value = 0
            for row in self.board:
                value += row[col]
            if value == self.size:
                return WinState.PLAYER_O
            elif value == -self.size:
                return WinState.PLAYER_X

        # Check diagonals
        diag_offset_1 = self.size - 1
        diag_offset_2 = 0
        value_1 = 0
        value_2 = 0
        for i in range(0, self.size):
            value_1 += self.board[i][diag_offset_1]
            value_2 += self.board[i][diag_offset_2]
            diag_offset_1 -= 1
            diag_offset_2 += 1
        if value_1 == self.size or value_2 == self.size:
            return WinState.PLAYER_O
        elif value_1 == -self.size or value_2 == -self.size:
            return WinState.PLAYER_X

        # Check if board is blocked
        if self.check_blocked():
            return WinState.TIE


@fun.command()
@lightbulb.option("size", "The size of the board. Default is 3.", type=int, required=False)
@lightbulb.option("user", "The user to play tic tac toe with!", type=hikari.Member)
@lightbulb.command("tictactoe", "Play tic tac toe with someone!")
@lightbulb.implements(lightbulb.SlashCommand)
async def tictactoe(ctx: lightbulb.SlashContext) -> None:
    size: int = ctx.options.size or 3

    if size not in (3, 4, 5):
        embed = hikari.Embed(
            title="❌ Invalid size",
            description=f"Size must be one of the following: `3`, `4`, `5`.",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    if ctx.options.user.id == ctx.author.id:
        embed = hikari.Embed(
            title="❌ Invoking self",
            description=f"I'm sorry, but how would that even work?",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    if not ctx.options.is_bot:
        embed = hikari.Embed(
            title="Tic Tac Toe!",
            description=f"**{ctx.options.user.username}** was challenged for a round of tic tac toe by **{ctx.member.username}**!\nFirst to a row of **{size} wins!**\nIt is **{ctx.member.username}**'s turn!",
            color=ctx.app.embed_blue,
        )
        embed.set_thumbnail(helpers.get_display_avatar(ctx.member))

        view = TicTacToeView(ctx.app, size, ctx.member, ctx.options.user)
        proxy = await ctx.respond(embed=embed, components=view.build())
        view.start(await proxy.message())

    else:
        embed = hikari.Embed(
            title="❌ Invalid user",
            description=f"Sorry, but you cannot play with a bot.. yet...",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@fun.command
@lightbulb.option("show_global", "To show the global avatar or not, if applicable", bool, required=False)
@lightbulb.option("user", "The user to show the avatar for.", hikari.Member, required=False)
@lightbulb.command("avatar", "Displays a user's avatar for your viewing pleasure.")
@lightbulb.implements(lightbulb.SlashCommand)
async def avatar(ctx: lightbulb.SlashContext) -> None:
    member = ctx.options.user or ctx.member
    if ctx.options.show_global == True:
        avatar_url = helpers.get_avatar(member)
    else:
        avatar_url = helpers.get_display_avatar(member)

    embed = hikari.Embed(title=f"{member.display_name}'s avatar:", color=helpers.get_color(member))
    embed.set_image(avatar_url)
    embed = helpers.add_embed_footer(embed, member)
    await ctx.respond(embed=embed)


@fun.command
@lightbulb.command("funfact", "Shows a random fun fact.")
@lightbulb.implements(lightbulb.SlashCommand)
async def funfact(ctx: lightbulb.SlashContext) -> None:
    fun_path = Path(ctx.app.base_dir, "etc", "funfacts.txt")
    fun_facts = open(fun_path, "r").readlines()
    embed = hikari.Embed(title="🤔 Did you know?", description=f"{random.choice(fun_facts)}", color=ctx.app.embed_blue)
    embed = helpers.add_embed_footer(embed, ctx.member)
    await ctx.respond(embed=embed)


@fun.command
@lightbulb.command("penguinfact", "Shows a fact about penguins.")
@lightbulb.implements(lightbulb.SlashCommand)
async def funfact(ctx: lightbulb.SlashContext) -> None:
    penguin_path = Path(ctx.app.base_dir, "etc", "penguinfacts.txt")
    penguin_facts = open(penguin_path, "r").readlines()
    embed = hikari.Embed(
        title="🐧 Penguin Fact", description=f"{random.choice(penguin_facts)}", color=ctx.app.embed_blue
    )
    embed = helpers.add_embed_footer(embed, ctx.member)
    await ctx.respond(embed=embed)


@fun.command
@lightbulb.command("randomcat", "Searches the interwebz™️ for a random cat picture.", auto_defer=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def randomcat(ctx: lightbulb.SlashContext) -> None:
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.thecatapi.com/v1/images/search") as response:
            if response.status == 200:
                catjson = await response.json()

                embed = hikari.Embed(title="🐱 Random kitten", color=ctx.app.embed_blue)
                embed.set_image(catjson[0]["url"])
            else:
                embed = hikari.Embed(
                    title="🐱 Random kitten",
                    description="Oops! Looks like the cat delivery service is unavailable! Check back later.",
                    color=ctx.app.error_color,
                )

            embed = helpers.add_embed_footer(embed, ctx.member)
            await ctx.respond(embed=embed)


def load(bot):
    logging.info("Adding plugin: Fun")
    bot.add_plugin(fun)


def unload(bot):
    logging.info("Removing plugin: Fun")
    bot.remove_plugin(fun)
