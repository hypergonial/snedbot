import asyncio
import datetime
import logging
import os
import random
import typing as t
from enum import IntEnum
from io import BytesIO
from pathlib import Path
from textwrap import fill

import hikari
import Levenshtein as lev
import lightbulb
import miru
from miru.ext import nav
from PIL import Image, ImageDraw, ImageFont

from config import Config
from etc import const
from models import SnedBot, SnedSlashContext
from models.checks import bot_has_permissions
from models.context import SnedContext, SnedUserContext
from models.plugin import SnedPlugin
from models.views import AuthorOnlyNavigator
from utils import BucketType, RateLimiter, helpers
from utils.dictionaryapi import (
    DictionaryClient,
    DictionaryEntry,
    DictionaryException,
    UrbanEntry,
)

ANIMAL_EMOJI_MAPPING: t.Dict[str, str] = {
    "dog": "🐶",
    "cat": "🐱",
    "panda": "🐼",
    "red_panda": "🐾",
    "bird": "🐦",
    "fox": "🦊",
    "racoon": "🦝",
}

animal_ratelimiter = RateLimiter(60, 45, BucketType.GLOBAL, wait=False)

logger = logging.getLogger(__name__)

if api_key := os.getenv("DICTIONARYAPI_API_KEY"):
    dictionary_client = DictionaryClient(api_key)
else:
    dictionary_client = None


@lightbulb.Check  # type: ignore
def has_dictionary_client(_: SnedContext) -> bool:
    if dictionary_client:
        return True
    raise DictionaryException("Dictionary API key not set.")


fun = SnedPlugin("Fun")


@fun.set_error_handler()
async def handle_errors(event: lightbulb.CommandErrorEvent) -> bool:
    if isinstance(event.exception, lightbulb.CheckFailure) and isinstance(
        event.exception.__cause__, DictionaryException
    ):
        await event.context.respond(
            embed=hikari.Embed(
                title="❌ No Dictionary API key provided",
                description="This command is currently unavailable.\n\n**Information:**\nPlease set the `DICTIONARYAPI_API_KEY` environment variable to use the Dictionary API.",
                color=const.ERROR_COLOR,
            )
        )
        return True

    return False


class WinState(IntEnum):
    PLAYER_X = 0
    PLAYER_O = 1
    TIE = 2


class TicTacToeButton(miru.Button):
    def __init__(self, x: int, y: int) -> None:
        super().__init__(style=hikari.ButtonStyle.SECONDARY, label="\u200b", row=y)
        self.x: int = x
        self.y: int = y

    async def callback(self, ctx: miru.Context) -> None:
        if not isinstance(self.view, TicTacToeView) or self.view.current_player.id != ctx.user.id:
            return

        view: TicTacToeView = self.view
        value: int = view.board[self.y][self.x]

        if value in (view.size, -view.size):  # If already clicked
            return

        if view.current_player.id == view.player_x.id:
            self.style = hikari.ButtonStyle.DANGER
            self.label = "X"
            self.disabled = True
            view.board[self.y][self.x] = -1
            view.current_player = view.player_o
            embed = hikari.Embed(
                title="Tic Tac Toe!",
                description=f"It is **{view.player_o.display_name}**'s turn!",
                color=0x009DFF,
            ).set_thumbnail(view.player_o.display_avatar_url)

        else:
            self.style = hikari.ButtonStyle.SUCCESS
            self.label = "O"
            self.disabled = True
            view.board[self.y][self.x] = 1
            view.current_player = view.player_x
            embed = hikari.Embed(
                title="Tic Tac Toe!",
                description=f"It is **{view.player_x.display_name}**'s turn!",
                color=0x009DFF,
            ).set_thumbnail(view.player_x.display_avatar_url)

        winner = view.check_winner()

        if winner is not None:

            if winner == WinState.PLAYER_X:
                embed = hikari.Embed(
                    title="Tic Tac Toe!",
                    description=f"**{view.player_x.display_name}** won!",
                    color=0x77B255,
                ).set_thumbnail(view.player_x.display_avatar_url)

            elif winner == WinState.PLAYER_O:
                embed = hikari.Embed(
                    title="Tic Tac Toe!",
                    description=f"**{view.player_o.display_name}** won!",
                    color=0x77B255,
                ).set_thumbnail(view.player_o.display_avatar_url)

            else:
                embed = hikari.Embed(title="Tic Tac Toe!", description=f"It's a tie!", color=0x77B255).set_thumbnail(
                    None
                )

            for button in view.children:
                assert isinstance(button, miru.Button)
                button.disabled = True

            view.stop()

        await ctx.edit_response(embed=embed, components=view)


class TicTacToeView(miru.View):
    def __init__(self, size: int, player_x: hikari.Member, player_o: hikari.Member, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.current_player: hikari.Member = player_x
        self.size: int = size
        self.player_x: hikari.Member = player_x
        self.player_o: hikari.Member = player_o

        self.board = [[0 for _ in range(size)] for _ in range(size)]

        for x in range(size):
            for y in range(size):
                self.add_item(TicTacToeButton(x, y))

    async def on_timeout(self) -> None:
        for item in self.children:
            assert isinstance(item, miru.Button)
            item.disabled = True

        assert self.message is not None

        await self.message.edit(
            embed=hikari.Embed(
                title="Tic Tac Toe!",
                description="This game timed out! Try starting a new one!",
                color=0xFF0000,
            ),
            components=self,
        )

    def check_blocked(self) -> bool:
        """
        Check if the board is blocked
        """
        blocked_list = [False, False, False, False]

        # TODO: Replace this old garbage

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

    def check_winner(self) -> t.Optional[WinState]:
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


class UrbanNavigator(AuthorOnlyNavigator):
    def __init__(self, lctx: lightbulb.Context, *, entries: t.List[UrbanEntry]) -> None:
        self.entries = entries
        pages = [
            hikari.Embed(
                title=entry.word,
                url=entry.jump_url,
                description=f"{entry.definition[:2000]}\n\n*{entry.example[:2000]}*",
                color=0xE86221,
                timestamp=entry.written_on,
            )
            .set_footer(f"by {entry.author}")
            .add_field("Votes", f"👍 {entry.thumbs_up} | 👎 {entry.thumbs_down}")
            for entry in self.entries
        ]
        super().__init__(lctx, pages=pages)  # type: ignore


class DictionarySelect(nav.NavSelect):
    def __init__(self, entries: t.List[DictionaryEntry]) -> None:
        options = [
            miru.SelectOption(
                label=f"{entry.word[:40]}{f' - ({entry.functional_label})' if entry.functional_label else ''}",
                description=f"{entry.definitions[0][:100] if entry.definitions else 'No definition found'}",
                value=str(i),
            )
            for i, entry in enumerate(entries)
        ]
        options[0].is_default = True
        super().__init__(options=options)

    async def before_page_change(self) -> None:
        for opt in self.options:
            opt.is_default = False

        self.options[self.view.current_page].is_default = True

    async def callback(self, context: miru.ViewContext) -> None:
        await self.view.send_page(context, int(self.values[0]))


class DictionaryNavigator(AuthorOnlyNavigator):
    def __init__(self, lctx: lightbulb.Context, *, entries: t.List[DictionaryEntry]) -> None:
        self.entries = entries
        pages = [
            hikari.Embed(
                title=f"📖 {entry.word[:40]}{f' - ({entry.functional_label})' if entry.functional_label else ''}",
                description="**Definitions:**\n"
                + "\n".join([f"**•** {definition[:512]}" for definition in entry.definitions])
                + (f"\n\n**Etymology:**\n*{entry.etymology[:1500]}*" if entry.etymology else ""),
                color=0xA5D732,
            ).set_footer("Provided by Merriam-Webster")
            for entry in self.entries
        ]
        super().__init__(lctx, pages=pages)  # type: ignore
        self.add_item(DictionarySelect(self.entries))


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option("size", "The size of the board. Default is 3.", required=False, choices=["3", "4", "5"])
@lightbulb.option("user", "The user to play tic tac toe with!", type=hikari.Member)
@lightbulb.command("tictactoe", "Play tic tac toe with someone!", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def tictactoe(ctx: SnedSlashContext, user: hikari.Member, size: t.Optional[str] = None) -> None:
    size_int = int(size or 3)
    helpers.is_member(user)
    assert ctx.member is not None

    if user.id == ctx.author.id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invoking self",
                description=f"I'm sorry, but how would that even work?",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if not user.is_bot:
        view = TicTacToeView(size_int, ctx.member, user)
        proxy = await ctx.respond(
            embed=hikari.Embed(
                title="Tic Tac Toe!",
                description=f"**{user.display_name}** was challenged for a round of tic tac toe by **{ctx.member.display_name}**!\nFirst to a row of **{size_int} wins!**\nIt is **{ctx.member.display_name}**'s turn!",
                color=const.EMBED_BLUE,
            ).set_thumbnail(ctx.member.display_avatar_url),
            components=view.build(),
        )
        await view.start(await proxy.message())

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid user",
                description=f"Sorry, but you cannot play with a bot.. yet...",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.set_max_concurrency(1, lightbulb.ChannelBucket)
@lightbulb.add_checks(bot_has_permissions(hikari.Permissions.ADD_REACTIONS))
@lightbulb.option("length", "The amount of words provided.", required=False, type=int, min_value=1, max_value=15)
@lightbulb.option(
    "difficulty", "The difficulty of the words provided.", choices=["easy", "medium", "hard"], required=False
)
@lightbulb.command("typeracer", "Start a typerace to see who can type the fastest!", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def typeracer(ctx: SnedSlashContext, difficulty: t.Optional[str] = None, length: t.Optional[int] = None) -> None:
    length = length or 5
    difficulty = difficulty or "medium"

    file = open(Path(ctx.app.base_dir, "etc", "text", f"words_{difficulty}.txt"), "r")
    words = [word.strip() for word in file.readlines()]

    text = " ".join([random.choice(words) for _ in range(0, length)])
    file.close()

    await ctx.respond(
        embed=hikari.Embed(
            title=f"🏁 Typeracing begins {helpers.format_dt(helpers.utcnow() + datetime.timedelta(seconds=10), style='R')}",
            description="Prepare your keyboard of choice!",
            color=const.EMBED_BLUE,
        )
    )

    await asyncio.sleep(10.0)

    def draw_text(text: str) -> BytesIO:
        font = Path(ctx.app.base_dir, "etc", "fonts", "roboto-slab.ttf")
        display_text = fill(text, 60)

        img = Image.new("RGBA", (1, 1), color=0)  # 1x1 transparent image
        draw = ImageDraw.Draw(img)
        outline = ImageFont.truetype(str(font), 42)
        text_font = ImageFont.truetype(str(font), 40)

        # Resize image for text
        textwidth, textheight = draw.textsize(display_text, outline)
        margin = 20
        img = img.resize((textwidth + margin, textheight + margin))
        draw = ImageDraw.Draw(img)

        draw.text((margin / 2, margin / 2), display_text, font=text_font, fill="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return buffer

    buffer: BytesIO = await asyncio.get_running_loop().run_in_executor(None, draw_text)

    await ctx.respond(
        embed=hikari.Embed(
            description="🏁 Type in the text from above as fast as you can!",
            color=const.EMBED_BLUE,
        ),
        attachment=hikari.Bytes(buffer.getvalue(), "sned_typerace.png"),
    )

    end_trigger = asyncio.Event()
    start = helpers.utcnow()
    winners = {}

    def predicate(event: hikari.GuildMessageCreateEvent) -> bool:
        message = event.message

        if not message.content:
            return False

        if ctx.channel_id == message.channel_id and text.lower() == message.content.lower():
            winners[message.author] = (helpers.utcnow() - start).total_seconds()
            asyncio.create_task(message.add_reaction("✅"))
            end_trigger.set()

        elif ctx.channel_id == message.channel_id and lev.distance(text.lower(), message.content.lower()) < 5:
            asyncio.create_task(message.add_reaction("❌"))

        return False

    msg_listener = asyncio.create_task(
        ctx.app.wait_for(hikari.GuildMessageCreateEvent, predicate=predicate, timeout=None)
    )

    try:
        await asyncio.wait_for(end_trigger.wait(), timeout=60)
    except asyncio.TimeoutError:
        await ctx.respond(
            embed=hikari.Embed(
                title="🏁 Typeracing results",
                description="Nobody was able to complete the typerace within **60** seconds. Typerace cancelled.",
                color=const.ERROR_COLOR,
            )
        )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="🏁 First Place",
                description=f"**{list(winners.keys())[0]}** finished first, everyone else has **15 seconds** to submit their reply!",
                color=const.EMBED_GREEN,
            )
        )
        await asyncio.sleep(15.0)

        desc = "**Participants:**\n"
        for winner in winners:
            desc = f"{desc}**#{list(winners.keys()).index(winner)+1}** **{winner}** `{round(winners[winner], 1)}` seconds - `{round((len(text) / 5) / (winners[winner] / 60))}`WPM\n"

        await ctx.respond(
            embed=hikari.Embed(
                title="🏁 Typeracing results",
                description=desc,
                color=const.EMBED_GREEN,
            )
        )

    msg_listener.cancel()


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.add_checks(has_dictionary_client)
@lightbulb.option("word", "The word to look up.", required=True, autocomplete=True)
@lightbulb.command("dictionary", "Look up a word in the dictionary!", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def dictionary_lookup(ctx: SnedSlashContext, word: str) -> None:
    assert dictionary_client is not None
    entries = await dictionary_client.get_mw_entries(word)

    channel = ctx.get_channel()
    is_nsfw = channel.is_nsfw if isinstance(channel, hikari.PermissibleGuildChannel) else False
    entries = [entry for entry in entries if is_nsfw or not is_nsfw and not entry.offensive]

    if not entries:
        embed = hikari.Embed(
            title="❌ Not found",
            description=f"No entries found for **{word}**.",
            color=const.ERROR_COLOR,
        )
        if not is_nsfw:
            embed.set_footer("Please note that certain offensive words are only accessible in NSFW channels.")

        await ctx.respond(embed=embed)
        return

    navigator = DictionaryNavigator(ctx, entries=entries)
    await navigator.send(ctx.interaction)


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.add_checks(has_dictionary_client)
@lightbulb.option("word", "The word to look up.", required=True)
@lightbulb.command("urban", "Look up a word in the Urban dictionary!", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def urban_lookup(ctx: SnedSlashContext, word: str) -> None:
    assert dictionary_client is not None
    entries = await dictionary_client.get_urban_entries(word)

    if not entries:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Not found",
                description=f"No entries found for **{word}**.",
                color=const.ERROR_COLOR,
            )
        )
        return

    navigator = UrbanNavigator(ctx, entries=entries)
    await navigator.send(ctx.interaction)


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option(
    "show_global",
    "To show the global avatar or not, if applicable",
    bool,
    required=False,
)
@lightbulb.option("user", "The user to show the avatar for.", hikari.Member, required=False)
@lightbulb.command("avatar", "Displays a user's avatar for your viewing pleasure.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def avatar(
    ctx: SnedSlashContext, user: t.Optional[hikari.Member] = None, show_global: t.Optional[bool] = None
) -> None:
    if user:
        helpers.is_member(user)
    member = user or ctx.member
    assert member is not None

    await ctx.respond(
        embed=hikari.Embed(title=f"{member.display_name}'s avatar:", color=helpers.get_color(member)).set_image(
            member.avatar_url if show_global else member.display_avatar_url
        )
    )


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.command("Show Avatar", "Displays the target's avatar for your viewing pleasure.", pass_options=True)
@lightbulb.implements(lightbulb.UserCommand)
async def avatar_context(ctx: SnedUserContext, target: t.Union[hikari.User, hikari.Member]) -> None:
    await ctx.respond(
        embed=hikari.Embed(
            title=f"{target.display_name if isinstance(target, hikari.Member) else target.username}'s avatar:",
            color=helpers.get_color(target) if isinstance(target, hikari.Member) else const.EMBED_BLUE,
        ).set_image(target.display_avatar_url),
        flags=hikari.MessageFlag.EPHEMERAL,
    )


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.command("funfact", "Shows a random fun fact.")
@lightbulb.implements(lightbulb.SlashCommand)
async def funfact(ctx: SnedSlashContext) -> None:
    fun_path = Path(ctx.app.base_dir, "etc", "text", "funfacts.txt")
    fun_facts = open(fun_path, "r").readlines()
    await ctx.respond(
        embed=hikari.Embed(
            title="🤔 Did you know?",
            description=f"{random.choice(fun_facts)}",
            color=const.EMBED_BLUE,
        )
    )


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.command("penguinfact", "Shows a fact about penguins.")
@lightbulb.implements(lightbulb.SlashCommand)
async def penguinfact(ctx: SnedSlashContext) -> None:
    penguin_path = Path(ctx.app.base_dir, "etc", "text", "penguinfacts.txt")
    penguin_facts = open(penguin_path, "r").readlines()
    await ctx.respond(
        embed=hikari.Embed(
            title="🐧 Penguin Fact",
            description=f"{random.choice(penguin_facts)}",
            color=const.EMBED_BLUE,
        )
    )


def roll_dice(amount: int, sides: int, show_sum: bool) -> hikari.Embed:
    """Roll dice & generate embed for user display.

    Parameters
    ----------
    amount : int
        Amount of dice to roll.
    sides : int
        The number of sides on the dice.
    show_sum : bool
        Determines if the sum is shown to the user or not.

    Returns
    -------
    hikari.Embed
        The diceroll results as an embed.
    """
    throws = [random.randint(1, sides) for _ in range(amount)]
    description = f'**Results (`{amount}d{sides}`):** {" ".join([f"`[{throw}]`" for throw in throws])}'

    if show_sum:
        description += f"\n**Sum:** `{sum(throws)}`"

    return hikari.Embed(
        title=f"🎲 Rolled the {'die' if amount == 1 else 'dice'}!",
        description=description,
        color=const.EMBED_BLUE,
    )


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option(
    "amount", "The amount of dice to roll. 1 by default.", required=False, type=int, min_value=1, max_value=20
)
@lightbulb.option(
    "sides",
    "The amount of sides a single die should have. 6 by default.",
    required=False,
    type=int,
    min_value=4,
    max_value=1000,
)
@lightbulb.option(
    "show_sum",
    "If true, shows the sum of the throws. False by default.",
    required=False,
    type=bool,
)
@lightbulb.command("dice", "Roll the dice!", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def dice(
    ctx: SnedSlashContext,
    sides: t.Optional[int] = None,
    amount: t.Optional[int] = None,
    show_sum: t.Optional[bool] = None,
) -> None:
    sides = sides or 6
    amount = amount or 1
    show_sum = show_sum or False

    await ctx.respond(
        embed=roll_dice(amount, sides, show_sum),
        components=miru.View().add_item(
            miru.Button(emoji="🎲", label="Reroll", custom_id=f"DICE:{amount}:{sides}:{int(show_sum)}:{ctx.author.id}")
        ),
    )


@fun.listener(miru.ComponentInteractionCreateEvent)
async def on_dice_reroll(event: miru.ComponentInteractionCreateEvent) -> None:
    if event.custom_id.startswith("DICE:"):
        amount, sides, show_sum, author_id = event.custom_id.split(":", maxsplit=1)[1].split(":")
        amount, sides, show_sum, author_id = int(amount), int(sides), bool(int(show_sum)), hikari.Snowflake(author_id)

        if event.author.id != author_id:
            await event.context.respond(
                embed=hikari.Embed(
                    title="❌ Cannot reroll",
                    description=f"Only the user who rolled the dice can reroll it.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        await event.context.edit_response(
            embed=roll_dice(amount, sides, show_sum),
            components=miru.View().add_item(
                miru.Button(
                    emoji="🎲",
                    label="Reroll",
                    custom_id=f"DICE:{amount}:{sides}:{int(show_sum)}:{event.context.author.id}",
                )
            ),
        )


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option(
    "animal", "The animal to show.", choices=["cat", "dog", "panda", "fox", "bird", "red_panda", "racoon"]
)
@lightbulb.command("animal", "Shows a random picture of the selected animal.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def animal(ctx: SnedSlashContext, animal: str) -> None:

    await animal_ratelimiter.acquire(ctx)
    if animal_ratelimiter.is_rate_limited(ctx):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Ratelimited",
                description=f"Please wait a couple minutes before trying again.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    async with ctx.bot.session.get(f"https://some-random-api.ml/img/{animal}") as response:
        if response.status != 200:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Network Error",
                    description=f"Could not access the API. Please try again later.",
                    color=const.ERROR_COLOR,
                )
            )
            return

        response = await response.json()
        await ctx.respond(
            embed=hikari.Embed(
                title=f"{ANIMAL_EMOJI_MAPPING[animal]} Random {animal.replace('_', ' ')}!",
                color=const.EMBED_BLUE,
            ).set_image(response["link"])
        )


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option("question", "The question you want to ask of the mighty 8ball.")
@lightbulb.command("8ball", "Ask a question, and the answers shall reveal themselves.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def eightball(ctx: SnedSlashContext, question: str) -> None:
    ball_path = Path(ctx.app.base_dir, "etc", "text", "8ball.txt")
    answers = open(ball_path, "r").readlines()
    await ctx.respond(
        embed=hikari.Embed(
            title=f"🎱 {question}",
            description=f"{random.choice(answers)}",
            color=const.EMBED_BLUE,
        )
    )


@fun.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option("query", "The query you want to search for on Wikipedia.")
@lightbulb.command("wiki", "Search Wikipedia for articles!", auto_defer=True, pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def wiki(ctx: SnedSlashContext, query: str) -> None:
    link = "https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=5"

    async with ctx.app.session.get(link.format(query=query)) as response:
        results = await response.json()
        results_text = results[1]
        results_link = results[3]

        if results_text:
            desc = "\n".join([f"[{result}]({results_link[i]})" for i, result in enumerate(results_text)])
            embed = hikari.Embed(
                title=f"Wikipedia: {query}",
                description=desc,
                color=const.MISC_COLOR,
            )
        else:
            embed = hikari.Embed(
                title="❌ No results",
                description="Could not find anything related to your query.",
                color=const.ERROR_COLOR,
            )
        await ctx.respond(embed=embed)


vesztettem_limiter = RateLimiter(1800, 1, BucketType.GLOBAL, wait=False)


@fun.listener(hikari.GuildMessageCreateEvent)
async def lose_autoresponse(event: hikari.GuildMessageCreateEvent) -> None:
    if event.guild_id not in (Config().DEBUG_GUILDS or (1012448659029381190,)) or not event.is_human:
        return

    if event.content and "vesztettem" in event.content.lower():
        await vesztettem_limiter.acquire(event.message)

        if vesztettem_limiter.is_rate_limited(event.message):
            return

        await event.message.respond("Vesztettem")


def load(bot: SnedBot) -> None:
    bot.add_plugin(fun)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(fun)


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
