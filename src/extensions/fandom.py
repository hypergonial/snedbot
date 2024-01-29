import arc
import hikari
import yarl

from src.config import Config
from src.etc import const
from src.models.client import SnedClient, SnedContext, SnedPlugin

plugin = SnedPlugin("Fandom")

FANDOM_QUERY_URL = "https://{site}.fandom.com/api.php?action=opensearch&search={query}&limit=5"


async def search_fandom(site: str, query: str) -> str | None:
    """Search a Fandom wiki with the specified query.

    Parameters
    ----------
    site : str
        The subdomain of the fandom wiki.
    query : str
        The query to search for.

    Returns
    -------
    Optional[str]
        A formatted string ready to display to the end user. `None` if no results were found.
    """
    async with plugin.client.session.get(yarl.URL(FANDOM_QUERY_URL.format(query=query, site=site))) as response:
        if response.status == 200:
            results = await response.json()
            if results[1]:
                return "\n".join([f"[{result}]({results[3][results[1].index(result)]})" for result in results[1]])
        else:
            raise RuntimeError(f"Failed to communicate with server. Response code: {response.status}")


@plugin.include
@arc.slash_command("fandom", "Search a Fandom wiki for articles!")
async def fandom_cmd(
    ctx: SnedContext,
    wiki: arc.Option[str, arc.StrParams("The wiki to get results from. This is the 'xxx.fandom.com' part of the URL.")],
    query: arc.Option[str, arc.StrParams("What are you looking for?")],
) -> None:
    try:
        if results := await search_fandom(wiki, query):
            embed = hikari.Embed(
                title=f"{wiki} Wiki: {query}",
                description=results,
                color=const.EMBED_BLUE,
            )
        else:
            embed = hikari.Embed(
                title="❌ Not found",
                description=f"Could not find anything for `{query}`",
                color=const.ERROR_COLOR,
            )
    except RuntimeError as e:
        embed = hikari.Embed(title="❌ Network Error", description=f"```{e}```", color=const.ERROR_COLOR)
    await ctx.respond(embed=embed)


@plugin.include
@arc.slash_command(
    "annowiki",
    "Search an Anno Wiki for articles!",
    guilds=Config().DEBUG_GUILDS or (581296099826860033, 372128553031958529),
)
async def annowiki_cmd(
    ctx: SnedContext,
    query: arc.Option[str, arc.StrParams("What are you looking for?")],
    wiki: arc.Option[
        str,
        arc.StrParams(
            "Choose the wiki to get results from. Defaults to 1800 if not specified.",
            choices=["1800", "2070", "2205", "1404"],
        ),
    ] = "1800",
) -> None:
    try:
        if results := await search_fandom(f"anno{wiki}", query):
            embed = hikari.Embed(
                title=f"Anno {wiki} Wiki: {query}",
                description=results,
                color=(218, 166, 100),
            )
        else:
            embed = hikari.Embed(
                title="❌ Not found",
                description=f"Could not find anything for `{query}`",
                color=const.ERROR_COLOR,
            )
    except RuntimeError as e:
        embed = hikari.Embed(title="❌ Network Error", description=f"```{e}```", color=const.ERROR_COLOR)
    await ctx.respond(embed=embed)


@plugin.include
@arc.slash_command(
    "ffwiki",
    "Search the Falling Frontier Wiki for articles!",
    guilds=Config().DEBUG_GUILDS or (684324252786360476, 813803567445049414),
)
async def ffwiki(
    ctx: SnedContext,
    query: arc.Option[str, arc.StrParams("What are you looking for?")],
) -> None:
    try:
        if results := await search_fandom("falling-frontier", query):
            embed = hikari.Embed(
                title=f"Falling Frontier Wiki: {query}",
                description=results,
                color=(75, 170, 147),
            )
        else:
            embed = hikari.Embed(
                title="❌ Not found",
                description=f"Could not find anything for `{query}`",
                color=const.ERROR_COLOR,
            )
    except RuntimeError as e:
        embed = hikari.Embed(title="❌ Network Error", description=f"```{e}```", color=const.ERROR_COLOR)
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
