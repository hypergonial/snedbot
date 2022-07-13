import aiohttp
import hikari
import lightbulb

from config import Config
from etc import constants as const
from models.bot import SnedBot
from models.context import SnedSlashContext
from models.plugin import SnedPlugin

fandom = SnedPlugin("Fandom")


async def search_fandom(site: str, query: str) -> str:
    """Search a Fandom wiki with the specified query.

    Parameters
    ----------
    site : str
        The subdomain of the fandom wiki.
    query : str
        The query to search for.

    Returns
    -------
    str
        A formatted string ready to display to the enduser.

    Raises
    ------
    ValueError
        No results were found.
    """
    link = "https://{site}.fandom.com/api.php?action=opensearch&search={query}&limit=5"

    query = query.replace(" ", "+")

    async with fandom.app.session.get(link.format(query=query, site=site)) as response:
        if response.status == 200:
            results = await response.json()
        else:
            raise RuntimeError(f"Failed to communicate with server. Response code: {response.status}")

    desc = ""
    if results[1]:  # 1 is text, 3 is links
        for result in results[1]:
            desc = f"{desc}[{result}]({results[3][results[1].index(result)]})\n"
        return desc
    else:
        raise ValueError("No results found for query.")


@fandom.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option("query", "What are you looking for?")
@lightbulb.option("wiki", "Choose the wiki to get results from. This is the 'xxxx.fandom.com' part of the URL.")
@lightbulb.command("fandom", "Search a Fandom wiki for articles!", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def fandom_cmd(ctx: SnedSlashContext, wiki: str, query: str) -> None:
    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    try:
        results = await search_fandom(wiki, query)
        embed = hikari.Embed(
            title=f"{wiki} Wiki: {query}",
            description=results,
            color=const.EMBED_BLUE,
        )
    except ValueError:
        embed = hikari.Embed(
            title="❌ Not found",
            description=f"Could not find anything for `{query}`",
            color=const.ERROR_COLOR,
        )
    except RuntimeError as e:
        embed = hikari.Embed(title="❌ Network Error", description=f"```{e}```", color=const.ERROR_COLOR)
    await ctx.respond(embed=embed)


@fandom.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option(
    "wiki",
    "Choose the wiki to get results from. Defaults to 1800 if not specified.",
    choices=["1800", "2070", "2205", "1404"],
    required=False,
)
@lightbulb.option("query", "What are you looking for?")
@lightbulb.command(
    "annowiki",
    "Search an Anno Wiki for articles!",
    pass_options=True,
    guilds=Config().DEBUG_GUILDS or (581296099826860033, 372128553031958529),
)
@lightbulb.implements(lightbulb.SlashCommand)
async def annowiki(ctx: SnedSlashContext, query: str, wiki: str = "1800") -> None:
    wiki = wiki or "1800"

    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    try:
        results = await search_fandom(f"anno{wiki}", query)
        embed = hikari.Embed(
            title=f"Anno {wiki} Wiki: {query}",
            description=results,
            color=(218, 166, 100),
        )
    except ValueError:
        embed = hikari.Embed(
            title="❌ Not found",
            description=f"Could not find anything for `{query}`",
            color=const.ERROR_COLOR,
        )
    except RuntimeError as e:
        embed = hikari.Embed(title="❌ Network Error", description=f"```{e}```", color=const.ERROR_COLOR)
    await ctx.respond(embed=embed)


@fandom.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option("query", "What are you looking for?")
@lightbulb.command(
    "ffwiki",
    "Search the Falling Frontier Wiki for articles!",
    pass_options=True,
    guilds=Config().DEBUG_GUILDS or (684324252786360476, 813803567445049414),
)
@lightbulb.implements(lightbulb.SlashCommand)
async def ffwiki(ctx: SnedSlashContext, query: str) -> None:
    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)
    try:
        results = await search_fandom(f"falling-frontier", query)
        embed = hikari.Embed(
            title=f"Falling Frontier Wiki: {query}",
            description=results,
            color=(75, 170, 147),
        )
    except ValueError:
        embed = hikari.Embed(
            title="❌ Not found",
            description=f"Could not find anything for `{query}`",
            color=const.ERROR_COLOR,
        )
    except RuntimeError as e:
        embed = hikari.Embed(title="❌ Network Error", description=f"```{e}```", color=const.ERROR_COLOR)
    await ctx.respond(embed=embed)


def load(bot: SnedBot) -> None:
    bot.add_plugin(fandom)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(fandom)


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
