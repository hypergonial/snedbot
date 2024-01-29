import asyncio
import datetime
import logging
import os
import random
from enum import IntEnum
from io import BytesIO
from pathlib import Path
from textwrap import fill
from typing import TYPE_CHECKING

import arc
import hikari
import Levenshtein as lev  # noqa: N813
import miru
from miru.ext import nav
from PIL import Image, ImageDraw, ImageFont

from src.etc import const
from src.models.client import SnedClient, SnedContext, SnedPlugin
from src.models.views import AuthorOnlyNavigator, AuthorOnlyView
from src.utils import GlobalBucket, RateLimiter, helpers
from src.utils.dictionaryapi import DictionaryClient, DictionaryEntry, DictionaryError, UrbanEntry
from src.utils.ratelimiter import UserBucket
from src.utils.rpn import InvalidExpressionError, Solver

from ..config import Config

if TYPE_CHECKING:
    from fractions import Fraction

ANIMAL_EMOJI_MAPPING: dict[str, str] = {
    "dog": "🐶",
    "cat": "🐱",
    "panda": "🐼",
    "red_panda": "🐾",
    "bird": "🐦",
    "fox": "🦊",
    "racoon": "🦝",
}

ANIMAL_RATELIMITER = RateLimiter(60, 45, GlobalBucket, wait=False)
COMF_LIMITER = RateLimiter(60, 5, UserBucket, wait=False)
VESZTETTEM_LIMITER = RateLimiter(1800, 1, GlobalBucket, wait=False)
COMF_PROGRESS_BAR_WIDTH = 20

logger = logging.getLogger(__name__)

dictionary_client = DictionaryClient(key) if (key := os.getenv("DICTIONARYAPI_API_KEY")) else None


def has_dictionary_client(_: SnedContext) -> None:
    if dictionary_client:
        return
    raise DictionaryError("Dictionary API key not set.")


plugin = SnedPlugin("Fun")


@plugin.set_error_handler()
async def handle_errors(ctx: SnedContext, exception: Exception) -> None:
    if isinstance(exception, DictionaryError):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ No Dictionary API key provided",
                description="This command is currently unavailable.\n\n**Information:**\nPlease set the `DICTIONARYAPI_API_KEY` environment variable to use the Dictionary API.",
                color=const.ERROR_COLOR,
            )
        )
        return

    raise exception


class AddBufButton(miru.Button):
    def __init__(self, value: str, *args, **kwargs):
        if "label" not in kwargs:
            kwargs["label"] = value
        super().__init__(*args, **kwargs)
        self.value = value

    async def callback(self, ctx: miru.ViewContext):
        assert isinstance(self.view, CalculatorView)
        if len(self.view._buf) > 100:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Expression too long", description="The expression is too long!", color=const.ERROR_COLOR
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return
        # Add a + after Ans if the user presses a number right after =
        if not self.view._buf and self.view._ans and self.value not in ("+", "-", "*", "/", "(", ")"):
            self.view._buf.append("+")
        self.view._buf.append(self.value)
        await self.view.refresh(ctx)


class RemBufButton(miru.Button):
    async def callback(self, ctx: miru.ViewContext):
        assert isinstance(self.view, CalculatorView)
        if self.view._buf:
            self.view._buf.pop()
        elif self.view._ans:
            self.view._ans = None
        await self.view.refresh(ctx)


class ClearBufButton(miru.Button):
    async def callback(self, ctx: miru.ViewContext):
        assert isinstance(self.view, CalculatorView)
        self.view._buf.clear()
        self.view._ans = None
        await self.view.refresh(ctx)


class EvalBufButton(miru.Button):
    async def callback(self, ctx: miru.ViewContext):
        assert isinstance(self.view, CalculatorView)
        if not self.view._buf:
            return
        # Inject the previous answer into the buffer
        if self.view._ans:
            self.view._buf.insert(0, str(self.view._ans))
        solver = Solver("".join(self.view._buf))
        try:
            result = solver.solve()
        except InvalidExpressionError as e:
            await ctx.edit_response(content=f"```ERR: {e}```")
        else:
            self.view._ans = result
            if not self.view._keep_frac:
                result = str(float(result))
                if result.endswith(".0"):
                    result = result[:-2]
            await ctx.edit_response(content=f"```{''.join(self.view._buf)}={result}```")
        self.view._clear_next = True


class CalculatorView(AuthorOnlyView):
    def __init__(self, author: hikari.PartialUser | hikari.Snowflakeish, keep_frac: bool = True) -> None:
        super().__init__(author, timeout=300)
        self._buf: list[str] = []
        self._clear_next = True
        self._keep_frac = keep_frac
        self._ans: Fraction | None = None
        buttons = [
            AddBufButton("(", style=hikari.ButtonStyle.PRIMARY, row=0),
            AddBufButton(")", style=hikari.ButtonStyle.PRIMARY, row=0),
            RemBufButton(label="<-", style=hikari.ButtonStyle.DANGER, row=0),
            ClearBufButton(label="C", style=hikari.ButtonStyle.DANGER, row=0),
            AddBufButton("1", style=hikari.ButtonStyle.SECONDARY, row=1),
            AddBufButton("2", style=hikari.ButtonStyle.SECONDARY, row=1),
            AddBufButton("3", style=hikari.ButtonStyle.SECONDARY, row=1),
            AddBufButton("+", style=hikari.ButtonStyle.PRIMARY, row=1),
            AddBufButton("4", style=hikari.ButtonStyle.SECONDARY, row=2),
            AddBufButton("5", style=hikari.ButtonStyle.SECONDARY, row=2),
            AddBufButton("6", style=hikari.ButtonStyle.SECONDARY, row=2),
            AddBufButton("-", style=hikari.ButtonStyle.PRIMARY, row=2),
            AddBufButton("7", style=hikari.ButtonStyle.SECONDARY, row=3),
            AddBufButton("8", style=hikari.ButtonStyle.SECONDARY, row=3),
            AddBufButton("9", style=hikari.ButtonStyle.SECONDARY, row=3),
            AddBufButton("*", style=hikari.ButtonStyle.PRIMARY, row=3),
            AddBufButton(".", style=hikari.ButtonStyle.SECONDARY, row=4),
            AddBufButton("0", style=hikari.ButtonStyle.SECONDARY, row=4),
            EvalBufButton(label="=", style=hikari.ButtonStyle.SUCCESS, row=4),
            AddBufButton("/", style=hikari.ButtonStyle.PRIMARY, row=4),
        ]
        for button in buttons:
            self.add_item(button)

    async def refresh(self, ctx: miru.ViewContext) -> None:
        if not self._buf:
            await ctx.edit_response(content="```Ans```" if self._ans else "```-```")
            return
        await ctx.edit_response(
            content=f"```Ans{''.join(self._buf)}```" if self._ans else f"```{''.join(self._buf)}```"
        )

    async def view_check(self, ctx: miru.ViewContext) -> bool:
        if not await super().view_check(ctx):
            return False

        # Clear buffer if solved or in error state
        if self._clear_next:
            self._buf.clear()
            self._clear_next = False

        return True

    async def on_timeout(self, ctx: miru.ViewContext) -> None:
        for item in self.children:
            item.disabled = True
        await ctx.edit_response(components=self)


class WinState(IntEnum):
    PLAYER_X = 0
    PLAYER_O = 1
    TIE = 2


class TicTacToeButton(miru.Button):
    def __init__(self, x: int, y: int) -> None:
        super().__init__(style=hikari.ButtonStyle.SECONDARY, label="\u200b", row=y)
        self.x: int = x
        self.y: int = y

    async def callback(self, ctx: miru.ViewContext) -> None:
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
                embed = hikari.Embed(title="Tic Tac Toe!", description="It's a tie!", color=0x77B255).set_thumbnail(
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
        """Check if the board is blocked."""
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

    def check_winner(self) -> WinState | None:
        """Check if there is a winner."""
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

        return None


class UrbanNavigator(AuthorOnlyNavigator):
    def __init__(self, author: hikari.PartialUser | hikari.Snowflakeish, *, entries: list[UrbanEntry]) -> None:
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
        super().__init__(author, pages=pages)  # type: ignore


class DictionarySelect(nav.NavTextSelect):
    def __init__(self, entries: list[DictionaryEntry]) -> None:
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
    def __init__(self, author: hikari.PartialUser | hikari.Snowflakeish, *, entries: list[DictionaryEntry]) -> None:
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
        super().__init__(author, pages=pages)  # type: ignore
        self.add_item(DictionarySelect(self.entries))


@plugin.include
@arc.slash_command("calc", "A calculator! If ran without options, an interactive calculator will be sent.")
async def calc(
    ctx: SnedContext,
    expr: arc.Option[
        str | None,
        arc.StrParams(
            "The mathematical expression to evaluate. If provided, interactive mode will not be used.", max_length=100
        ),
    ] = None,
    display: arc.Option[
        str, arc.StrParams("The display mode to use for the result.", choices=["fractional", "decimal"])
    ] = "decimal",
) -> None:
    if not expr:
        view = CalculatorView(ctx.author, display == "fractional")
        await ctx.respond("```-```", components=view)
        ctx.client.miru.start_view(view)
        return

    solver = Solver(expr)
    try:
        result = solver.solve()
    except InvalidExpressionError as e:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid Expression",
                description=f"Error encountered evaluating expression: ```{e}```",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if display == "fractional":
        await ctx.respond(content=f"```{expr} = {result}```")
    else:
        result = str(float(result))
        if result.endswith(".0"):
            result = result[:-2]
        await ctx.respond(content=f"```{expr} = {result}```")


@plugin.include
@arc.slash_command("tictactoe", "Play tic tac toe with someone!")
async def tictactoe(
    ctx: SnedContext,
    user: arc.Option[hikari.User, arc.UserParams("The user to play tic tac toe with!")],
    size: arc.Option[int, arc.IntParams("The size of the board. Default is 3.", choices=[3, 4, 5])] = 3,
) -> None:
    if not helpers.is_member(user):
        return
    assert ctx.member is not None

    if user.id == ctx.author.id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invoking self",
                description="I'm sorry, but how would that even work?",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    if user.is_bot:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid user",
                description="Sorry, but you cannot play with a bot.. yet...",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    view = TicTacToeView(size, ctx.member, user)
    await ctx.respond(
        embed=hikari.Embed(
            title="Tic Tac Toe!",
            description=f"**{user.display_name}** was challenged for a round of tic tac toe by **{ctx.member.display_name}**!\nFirst to a row of **{size} wins!**\nIt is **{ctx.member.display_name}**'s turn!",
            color=const.EMBED_BLUE,
        ).set_thumbnail(ctx.member.display_avatar_url),
        components=view,
    )
    ctx.client.miru.start_view(view)


@plugin.include
@arc.with_concurrency_limit(arc.channel_concurrency(1))
@arc.with_hook(arc.has_permissions(hikari.Permissions.ADD_REACTIONS | hikari.Permissions.VIEW_CHANNEL))
@arc.slash_command("typeracer", "Start a typerace to see who can type the fastest!")
async def typeracer(
    ctx: SnedContext,
    difficulty: arc.Option[
        str, arc.StrParams("The difficulty of the words provided.", choices=["easy", "medium", "hard"])
    ] = "medium",
    length: arc.Option[int, arc.IntParams("The amount of words provided.", min=1, max=15)] = 5,
) -> None:
    with open(Path(ctx.client.base_dir, "src", "etc", "text", f"words_{difficulty}.txt"), "r") as file:
        words = [word.strip() for word in file.readlines()]

        text = " ".join([random.choice(words) for _ in range(0, length)])

    resp = await ctx.respond(
        embed=hikari.Embed(
            title=f"🏁 Typeracing begins {helpers.format_dt(helpers.utcnow() + datetime.timedelta(seconds=10), style='R')}",
            description="Prepare your keyboard of choice!",
            color=const.EMBED_BLUE,
        )
    )

    await asyncio.sleep(9.0)  # We sleep for less to roughly account for network delay

    def draw_text() -> BytesIO:
        font = Path(ctx.client.base_dir, "src", "etc", "fonts", "roboto-slab.ttf")
        display_text = fill(text, 60)

        img = Image.new("RGBA", (1, 1), color=0)  # 1x1 transparent image
        draw = ImageDraw.Draw(img)
        outline = ImageFont.truetype(str(font), 42)
        text_font = ImageFont.truetype(str(font), 40)

        # Resize image for text
        lines = display_text.splitlines()
        logger.info(lines)
        textwidth = draw.textlength(lines[0], font=outline)
        margin = 20

        img = img.resize((int(textwidth) + margin, len(lines) * (42 + margin)))
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

    await resp.edit(
        embed=hikari.Embed(
            title=f"🏁 Typeracing began {helpers.format_dt(helpers.utcnow(), style='R')}",
            color=const.EMBED_BLUE,
        )
    )

    end_trigger = asyncio.Event()
    start = helpers.utcnow()
    winners = {}

    def predicate(event: hikari.GuildMessageCreateEvent) -> bool:
        message = event.message

        if not message.content:
            return False

        if ctx.channel_id != message.channel_id:
            return False

        if text.lower() == message.content.lower():
            winners[message.author] = (helpers.utcnow() - start).total_seconds()
            asyncio.create_task(message.add_reaction("✅"))  # noqa: RUF006
            end_trigger.set()

        elif lev.distance(text.lower(), message.content.lower()) < 5:
            asyncio.create_task(message.add_reaction("❌"))  # noqa: RUF006

        return False

    msg_listener = asyncio.create_task(
        ctx.client.app.wait_for(hikari.GuildMessageCreateEvent, predicate=predicate, timeout=None)
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
        return

    await ctx.respond(
        embed=hikari.Embed(
            title="🏁 First Place",
            description=f"**{next(iter(winners.keys()))}** finished first, everyone else has **15 seconds** to submit their reply!",
            color=const.EMBED_GREEN,
        )
    )
    await asyncio.sleep(15.0)
    msg_listener.cancel()

    desc = "**Participants:**\n"
    winner_keys = list(winners.keys())
    for winner in winners:
        desc = f"{desc}**#{winner_keys.index(winner)+1}** **{winner}** `{round(winners[winner], 1)}` seconds - `{round((len(text) / 5) / (winners[winner] / 60))}`WPM\n"

    await ctx.respond(
        embed=hikari.Embed(
            title="🏁 Typeracing results",
            description=desc,
            color=const.EMBED_GREEN,
        )
    )


@plugin.include
@arc.with_hook(has_dictionary_client)
@arc.slash_command("dictionary", "Look up a word in the dictionary!")
async def dictionary_lookup(ctx: SnedContext, word: arc.Option[str, arc.StrParams("The word to look up.")]) -> None:
    assert dictionary_client is not None
    entries = await dictionary_client.fetch_mw_entries(word)

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

    navigator = DictionaryNavigator(ctx.author, entries=entries)
    await ctx.respond_with_builder(await navigator.build_response_async(ctx.client.miru))
    ctx.client.miru.start_view(navigator)


@plugin.include
@arc.with_hook(has_dictionary_client)
@arc.slash_command("urban", "Look up a word in the Urban dictionary!")
async def urban_lookup(ctx: SnedContext, word: arc.Option[str, arc.StrParams("The word to look up.")]) -> None:
    assert dictionary_client is not None
    entries = await dictionary_client.fetch_urban_entries(word)

    if not entries:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Not found",
                description=f"No entries found for **{word}**.",
                color=const.ERROR_COLOR,
            )
        )
        return

    navigator = UrbanNavigator(ctx.author, entries=entries)
    await ctx.respond_with_builder(await navigator.build_response_async(ctx.client.miru))
    ctx.client.miru.start_view(navigator)


@plugin.include
@arc.slash_command("avatar", "Displays a user's avatar for your viewing pleasure.")
async def avatar(
    ctx: SnedContext,
    user: arc.Option[hikari.User | None, arc.UserParams("The user to show the avatar for.")] = None,
    show_global: arc.Option[bool, arc.BoolParams("To show the global avatar or not, if applicable.")] = False,
) -> None:
    if user and not helpers.is_member(user):
        return
    member = user or ctx.member
    assert member is not None

    await ctx.respond(
        embed=hikari.Embed(title=f"{member.display_name}'s avatar:", color=helpers.get_color(member)).set_image(
            member.avatar_url if show_global else member.display_avatar_url
        )
    )


@plugin.include
@arc.user_command("Show Avatar")
async def avatar_context(ctx: SnedContext, target: hikari.User) -> None:
    await ctx.respond(
        embed=hikari.Embed(
            title=f"{target.display_name if isinstance(target, hikari.Member) else target.username}'s avatar:",
            color=helpers.get_color(target) if isinstance(target, hikari.Member) else const.EMBED_BLUE,
        ).set_image(target.display_avatar_url),
        flags=hikari.MessageFlag.EPHEMERAL,
    )


@plugin.include
@arc.slash_command("funfact", "Shows a random fun fact.")
async def funfact(ctx: SnedContext) -> None:
    fun_path = Path(ctx.client.base_dir, "src", "etc", "text", "funfacts.txt")
    with open(fun_path, "r") as file:
        fun_facts = file.readlines()
        await ctx.respond(
            embed=hikari.Embed(
                title="🤔 Did you know?",
                description=f"{random.choice(fun_facts)}",
                color=const.EMBED_BLUE,
            )
        )


@plugin.include
@arc.slash_command("penguinfact", "Shows a fact about penguins.")
async def penguinfact(ctx: SnedContext) -> None:
    penguin_path = Path(ctx.client.base_dir, "src", "etc", "text", "penguinfacts.txt")
    with open(penguin_path, "r") as file:
        penguin_facts = file.readlines()
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


@plugin.include
@arc.slash_command("roll", "Roll the dice!")
async def dice(
    ctx: SnedContext,
    sides: arc.Option[int, arc.IntParams("The amount of sides a single die should have.", min=2, max=1000)],
    amount: arc.Option[int, arc.IntParams("The amount of dice to roll.", min=1, max=20)] = 1,
    show_sum: arc.Option[bool, arc.BoolParams("If true, shows the sum of the throws.")] = False,
) -> None:
    await ctx.respond(
        embed=roll_dice(amount, sides, show_sum),
        components=miru.View().add_item(
            miru.Button(emoji="🎲", label="Reroll", custom_id=f"DICE:{amount}:{sides}:{int(show_sum)}:{ctx.author.id}")
        ),
    )


@plugin.listen()
async def on_dice_reroll(event: hikari.InteractionCreateEvent) -> None:
    if not isinstance(event.interaction, hikari.ComponentInteraction):
        return

    inter = event.interaction

    if inter.custom_id.startswith("DICE:"):
        amount_str, sides_str, show_sum_str, author_id_str = inter.custom_id.split(":", maxsplit=1)[1].split(":")
        amount, sides, show_sum, author_id = (
            int(amount_str),
            int(sides_str),
            bool(int(show_sum_str)),
            hikari.Snowflake(author_id_str),
        )

        if inter.user.id != author_id:
            await inter.create_initial_response(
                hikari.ResponseType.MESSAGE_CREATE,
                embed=hikari.Embed(
                    title="❌ Cannot reroll",
                    description="Only the user who rolled the dice can reroll it.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        await inter.create_initial_response(
            hikari.ResponseType.MESSAGE_UPDATE,
            embed=roll_dice(amount, sides, show_sum),
            components=miru.View().add_item(
                miru.Button(
                    emoji="🎲",
                    label="Reroll",
                    custom_id=f"DICE:{amount}:{sides}:{int(show_sum)}:{inter.user.id}",
                )
            ),
        )


@plugin.include
@arc.with_hook(arc.global_limiter(60.0, 45))
@arc.slash_command("animal", "Shows a random picture of the selected animal.")
async def animal(
    ctx: SnedContext,
    animal: arc.Option[
        str, arc.StrParams("The animal to show.", choices=["cat", "dog", "panda", "fox", "bird", "red_panda", "racoon"])
    ],
) -> None:
    async with ctx.client.session.get(f"https://some-random-api.com/img/{animal}") as response:
        if response.status != 200:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Network Error",
                    description="Could not access the API. Please try again later.",
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


@plugin.include
@arc.slash_command("8ball", "Ask a question, and the answers shall reveal themselves.")
async def eightball(
    ctx: SnedContext, question: arc.Option[str, arc.StrParams("The question you want to ask of the mighty 8ball.")]
) -> None:
    ball_path = Path(ctx.client.base_dir, "src", "etc", "text", "8ball.txt")
    with open(ball_path, "r") as file:
        answers = file.readlines()
        await ctx.respond(
            embed=hikari.Embed(
                title=f"🎱 {question}",
                description=f"{random.choice(answers)}",
                color=const.EMBED_BLUE,
            )
        )


@plugin.include
@arc.slash_command("wiki", "Search Wikipedia for articles!")
async def wiki(
    ctx: SnedContext, query: arc.Option[str, arc.StrParams("The query you want to search for on Wikipedia.")]
) -> None:
    link = "https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=5"

    async with ctx.client.session.get(link.format(query=query)) as response:
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


@plugin.listen()
async def lose_autoresponse(event: hikari.GuildMessageCreateEvent) -> None:
    if event.guild_id not in (Config().DEBUG_GUILDS or (1012448659029381190,)) or not event.is_human:
        return

    if event.content and "vesztettem" in event.content.lower():
        await VESZTETTEM_LIMITER.acquire(event.message)

        if VESZTETTEM_LIMITER.is_rate_limited(event.message):
            return

        await event.message.respond("Vesztettem")


@plugin.include
@arc.with_hook(arc.global_limiter(60.0, 5))
@arc.slash_command("comf", "Shows your current and upcoming comfiness.")
async def comf(ctx: SnedContext) -> None:
    assert ctx.member is not None

    now = await helpers.usernow(ctx.client, ctx.author)
    today = datetime.datetime.combine(now.date(), datetime.time(0, 0), tzinfo=now.tzinfo)
    dates = [today + datetime.timedelta(days=delta_day + 1) for delta_day in range(3)]

    embed = (
        hikari.Embed(
            title=f"Comfiness forecast for {ctx.member.display_name}",
            description="Your forecasted comfiness is:",
            color=const.EMBED_BLUE,
        )
        .set_footer(
            f"Powered by the api.fraw.st oracle. {f'Timezone: {now.tzinfo.tzname(now)}' if now.tzinfo is not None else ''}"
        )
        .set_thumbnail(ctx.member.display_avatar_url)
    )

    for date in dates:
        params = {"id": str(ctx.author.id), "date": date.strftime("%Y-%m-%d %H:%M:%S")}
        async with ctx.client.session.get("https://api.fraw.st/comf", params=params) as response:
            if response.status != 200:
                await ctx.respond(
                    embed=hikari.Embed(
                        title="❌ Network Error",
                        description="Could not access our certified comfiness oracle. Please try again later.",
                        color=const.ERROR_COLOR,
                    ),
                    flags=hikari.MessageFlag.EPHEMERAL,
                )
                return

            response = await response.json()
            comf_value: float = response["comfValue"]
            rounded_comf = int(comf_value * COMF_PROGRESS_BAR_WIDTH / 100)

            progress_bar = "█" * rounded_comf + " " * (COMF_PROGRESS_BAR_WIDTH - rounded_comf)
            embed.add_field(f"**{date.strftime('%B %d, %Y')}**", f"`[{progress_bar}]` {comf_value:.1f}%")

    await ctx.respond(embed=embed)


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
