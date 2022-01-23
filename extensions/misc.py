import logging
import re

import hikari
import lightbulb
import miru
import psutil
from objects.utils import helpers

logger = logging.getLogger(__name__)

misc = lightbulb.Plugin("Miscellaneous Commands")
psutil.cpu_percent(interval=1)  # Call so subsequent calls for CPU % will not be blocking


@misc.command()
@lightbulb.command("ping", "Check the bot's latency.")
@lightbulb.implements(lightbulb.SlashCommand)
async def ping(ctx: lightbulb.SlashContext) -> None:
    embed = hikari.Embed(
        title="🏓 Pong!",
        description="Latency: `{latency}ms`".format(latency=round(ctx.app.heartbeat_latency * 1000)),
        color=ctx.app.misc_color,
    )
    embed = helpers.add_embed_footer(embed, ctx.member)
    await ctx.respond(embed=embed)


@misc.command()
@lightbulb.option(
    "color",
    "The color of the embed. Expects three space-separated values for an RGB value.",
    type=hikari.Color,
    required=False,
)
@lightbulb.option("author_url", "An URL to direct users to if the author is clicked.", required=False)
@lightbulb.option("author_image_url", "An URL pointing to an image to use for the author's avatar.", required=False)
@lightbulb.option("author", "The author of the embed. Appears above the title.", required=False)
@lightbulb.option("footer_image_url", "An url pointing to an image to use for the embed footer.", required=False)
@lightbulb.option("image_url", "An url pointing to an image to use for the embed image.", required=False)
@lightbulb.option("thumbnail_url", "An url pointing to an image to use for the thumbnail.", required=False)
@lightbulb.option("footer", "The footer of the embed.", required=False)
@lightbulb.option("description", "The description of the embed.", required=False)
@lightbulb.option("title", "The title of the embed. Required.")
@lightbulb.command("embed", "Generates a new embed with the parameters specified.")
@lightbulb.implements(lightbulb.SlashCommand)
async def embed(ctx: lightbulb.SlashContext) -> None:
    url_options = [
        ctx.options.image_url,
        ctx.options.thumbnail_url,
        ctx.options.footer_image_url,
        ctx.options.author_image_url,
        ctx.options.author_url,
    ]
    for option in url_options:
        if option and not helpers.is_url(option):
            embed = hikari.Embed(
                title="❌ Invalid URL",
                description=f"Provided an invalid URL.",
                color=ctx.app.error_color,
            )
            return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    embed = hikari.Embed(title=ctx.options.title, description=ctx.options.description, color=ctx.options.color)
    embed.set_footer(ctx.options.footer, icon=ctx.options.footer_image_url)
    embed.set_image(ctx.options.image_url)
    embed.set_thumbnail(ctx.options.thumbnail_url)
    embed.set_author(name=ctx.options.author, url=ctx.options.author_url, icon=ctx.options.author_image_url)

    await ctx.respond(embed=embed)


@embed.set_error_handler()
async def embed_error(event: lightbulb.CommandErrorEvent) -> None:
    if isinstance(event.exception, lightbulb.CommandInvocationError) and isinstance(
        event.exception.original, ValueError
    ):
        embed = hikari.Embed(
            title="❌ Parsing error",
            description=f"An error occurred parsing parameters.\n**Error:** ```{event.exception.original}```",
            color=event.context.app.error_color,
        )
        return await event.context.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
    raise


@misc.command()
@lightbulb.command("about", "Displays information about the bot.")
@lightbulb.implements(lightbulb.SlashCommand)
async def about(ctx: lightbulb.SlashContext) -> None:
    me = ctx.app.get_me()
    embed = hikari.Embed(
        title=f"ℹ️ About {me.username}",
        description=f"""**• Made by:** `Hyper#0001`
**• Servers:** `{len(ctx.app.cache.get_guilds_view())}`
**• Invite:** [Invite me!](https://discord.com/oauth2/authorize?client_id={me.id}&permissions=1643161053254&scope=bot%20applications.commands)
**• Support:** [Click here!](https://discord.gg/KNKr8FPmJa)\n
Blob emoji is licensed under [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0.html)""",
        color=ctx.app.embed_blue,
    )
    embed = helpers.add_embed_footer(embed, ctx.member)
    embed.set_thumbnail(me.avatar_url)
    embed.add_field(name="CPU utilization", value=f"`{round(psutil.cpu_percent(interval=None))}%`", inline=True)
    process = psutil.Process()  # gets current process
    embed.add_field(name="Memory utilization", value=f"`{round(process.memory_info().vms / 1048576)}MB`", inline=True)
    embed.add_field(name="Latency", value=f"`{round(ctx.app.heartbeat_latency * 1000)}ms`", inline=True)
    await ctx.respond(embed=embed)


@misc.command()
@lightbulb.command("invite", "Invite the bot to your server!")
@lightbulb.implements(lightbulb.SlashCommand)
async def invite(ctx: lightbulb.SlashContext) -> None:
    if not ctx.app.experimental:
        invite_url = f"https://discord.com/oauth2/authorize?client_id={ctx.app.get_me().id}&permissions=1643161053254&scope=applications.commands%20bot"
        embed = hikari.Embed(
            title="🌟 Yay!",
            description=f"[Click here]({invite_url}) for an invite link!",
            color=ctx.app.misc_color,
        )
        embed = helpers.add_embed_footer(embed, ctx.member)
        await ctx.respond(embed=embed)
    else:
        embed = hikari.Embed(
            title="🌟 Oops!",
            description=f"It looks like this bot is in developer mode, and not intended to be invited!",
            color=ctx.app.misc_color,
        )
        embed = helpers.add_embed_footer(embed, ctx.member)
        await ctx.respond(embed=embed)


@misc.command()
@lightbulb.command("support", "Provides a link to the support Discord.")
@lightbulb.implements(lightbulb.SlashCommand)
async def support(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond("https://discord.gg/KNKr8FPmJa")


@misc.command()
@lightbulb.command("source", "Provides a link to the source-code of the bot.")
@lightbulb.implements(lightbulb.SlashCommand)
async def support(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond("<https://github.com/HyperGH/snedbot_v2>")


@misc.command()
@lightbulb.command("serverinfo", "Provides detailed information about this server.")
@lightbulb.implements(lightbulb.SlashCommand)
async def serverinfo(ctx: lightbulb.SlashContext) -> None:
    guild = ctx.app.cache.get_available_guild(ctx.guild_id)

    embed = hikari.Embed(
        title=f"ℹ️ Server Information",
        description=f"""**• Name:** `{guild.name}`
**• ID:** `{guild.id}`
**• Owner:** `{ctx.app.cache.get_member(guild.id, guild.owner_id)}` (`{guild.owner_id}`)
**• Created at:** {helpers.format_dt(guild.created_at)} ({helpers.format_dt(guild.created_at, style="R")})
**• Member count:** `{guild.member_count}`
**• Roles:** `{len(guild.get_roles())}`
**• Channels:** `{len(guild.get_channels())}`
**• Nitro Boost level:** `{guild.premium_tier}`
**• Nitro Boost count:** `{guild.premium_subscription_count}`
**• Preferred locale:** `{guild.preferred_locale}`
**• Community:** `{"Yes" if "COMMUNITY" in guild.features else "No"}`
**• Partner:** `{"Yes" if "PARTNERED" in guild.features else "No"}`
**• Verified:** `{"Yes" if "VERIFIED" in guild.features else "No"}`
**• Discoverable:** `{"Yes" if "DISCOVERABLE" in guild.features else "No"}`
**• Monetization enabled:** `{"Yes" if "MONETIZATION_ENABLED" in guild.features else "No"}`
{f"**• Vanity URL:** {guild.vanity_url_code}" if guild.vanity_url_code else ""}
""",
        color=ctx.app.embed_blue,
    )

    embed = helpers.add_embed_footer(embed, ctx.member)
    embed.set_thumbnail(guild.icon_url)
    embed.set_image(guild.banner_url)

    await ctx.respond(embed=embed)


def load(bot):
    logging.info("Adding plugin: Miscellaneous Commands")
    bot.add_plugin(misc)


def unload(bot):
    logging.info("Removing plugin: Miscellaneous Commands")
    bot.remove_plugin(misc)
