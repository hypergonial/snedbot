from difflib import get_close_matches
import logging

import hikari
import lightbulb
import psutil
import miru
import pytz
import typing as t
from models.context import SnedMessageContext, SnedSlashContext
from utils import helpers
from models import SnedBot

logger = logging.getLogger(__name__)

misc = lightbulb.Plugin("Miscellaneous Commands")
psutil.cpu_percent(interval=1)  # Call so subsequent calls for CPU % will not be blocking


@misc.command()
@lightbulb.command("ping", "Check the bot's latency.")
@lightbulb.implements(lightbulb.SlashCommand)
async def ping(ctx: SnedSlashContext) -> None:
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
@lightbulb.option(
    "author_image_url",
    "An URL pointing to an image to use for the author's avatar.",
    required=False,
)
@lightbulb.option("author", "The author of the embed. Appears above the title.", required=False)
@lightbulb.option(
    "footer_image_url",
    "An url pointing to an image to use for the embed footer.",
    required=False,
)
@lightbulb.option(
    "image_url",
    "An url pointing to an image to use for the embed image.",
    required=False,
)
@lightbulb.option(
    "thumbnail_url",
    "An url pointing to an image to use for the thumbnail.",
    required=False,
)
@lightbulb.option("footer", "The footer of the embed.", required=False)
@lightbulb.option("description", "The description of the embed.", required=False)
@lightbulb.option("title", "The title of the embed. Required.")
@lightbulb.command("embed", "Generates a new embed with the parameters specified.")
@lightbulb.implements(lightbulb.SlashCommand)
async def embed(ctx: SnedSlashContext) -> None:
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

    embed = hikari.Embed(
        title=ctx.options.title,
        description=ctx.options.description,
        color=ctx.options.color,
    )
    embed.set_footer(ctx.options.footer, icon=ctx.options.footer_image_url)
    embed.set_image(ctx.options.image_url)
    embed.set_thumbnail(ctx.options.thumbnail_url)
    embed.set_author(
        name=ctx.options.author,
        url=ctx.options.author_url,
        icon=ctx.options.author_image_url,
    )

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
async def about(ctx: SnedSlashContext) -> None:
    me = ctx.app.get_me()
    embed = hikari.Embed(
        title=f"ℹ️ About {me.username}",
        description=f"""**• Made by:** `Hyper#0001`
**• Servers:** `{len(ctx.app.cache.get_guilds_view())}`
**• Invite:** [Invite me!](https://discord.com/oauth2/authorize?client_id={me.id}&permissions=1494984682710&scope=bot%20applications.commands)
**• Support:** [Click here!](https://discord.gg/KNKr8FPmJa)\n
Blob emoji is licensed under [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0.html)""",
        color=ctx.app.embed_blue,
    )
    embed = helpers.add_embed_footer(embed, ctx.member)
    embed.set_thumbnail(me.avatar_url)
    embed.add_field(
        name="CPU utilization",
        value=f"`{round(psutil.cpu_percent(interval=None))}%`",
        inline=True,
    )
    process = psutil.Process()  # gets current process
    embed.add_field(
        name="Memory utilization",
        value=f"`{round(process.memory_info().vms / 1048576)}MB`",
        inline=True,
    )
    embed.add_field(
        name="Latency",
        value=f"`{round(ctx.app.heartbeat_latency * 1000)}ms`",
        inline=True,
    )
    await ctx.respond(embed=embed)


@misc.command()
@lightbulb.command("invite", "Invite the bot to your server!")
@lightbulb.implements(lightbulb.SlashCommand)
async def invite(ctx: SnedSlashContext) -> None:
    if not ctx.app.dev_mode:
        invite_url = f"https://discord.com/oauth2/authorize?client_id={ctx.app.user_id}&permissions=1494984682710&scope=applications.commands%20bot"
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
@lightbulb.add_cooldown(10.0, 1, lightbulb.GuildBucket)
@lightbulb.add_checks(
    lightbulb.has_guild_permissions(hikari.Permissions.MANAGE_NICKNAMES),
    lightbulb.bot_has_guild_permissions(hikari.Permissions.CHANGE_NICKNAME),
)
@lightbulb.option("nickname", "The nickname to set the bot's nickname to. Type 'None' to reset it!")
@lightbulb.command("setnick", "Set the bot's nickname!")
@lightbulb.implements(lightbulb.SlashCommand)
async def setnick(ctx: SnedSlashContext) -> None:
    nickname = ctx.options.nickname[:32] if not ctx.options.nickname.lower() == "none" else None

    await ctx.app.rest.edit_my_member(
        ctx.guild_id, nickname=nickname, reason=f"Nickname changed via /setnick by {ctx.author}"
    )
    embed = hikari.Embed(title="✅ Nickname changed!", color=ctx.app.embed_green)
    await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@misc.command()
@lightbulb.command("support", "Provides a link to the support Discord.")
@lightbulb.implements(lightbulb.SlashCommand)
async def support(ctx: SnedSlashContext) -> None:
    await ctx.respond("https://discord.gg/KNKr8FPmJa", flags=hikari.MessageFlag.EPHEMERAL)


@misc.command()
@lightbulb.command("source", "Provides a link to the source-code of the bot.")
@lightbulb.implements(lightbulb.SlashCommand)
async def source(ctx: SnedSlashContext) -> None:
    await ctx.respond("<https://github.com/HyperGH/snedbot_v2>")


@misc.command()
@lightbulb.command("serverinfo", "Provides detailed information about this server.")
@lightbulb.implements(lightbulb.SlashCommand)
async def serverinfo(ctx: SnedSlashContext) -> None:
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
**• Nitro Boost count:** `{guild.premium_subscription_count or '*Not found*'}`
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


@misc.command()
@lightbulb.add_checks(
    lightbulb.bot_has_role_permissions(hikari.Permissions.SEND_MESSAGES, hikari.Permissions.VIEW_CHANNEL),
    lightbulb.has_guild_permissions(hikari.Permissions.MANAGE_MESSAGES),
)
@lightbulb.option(
    "channel",
    "The channel to send the message to, defaults to the current channel.",
    required=False,
    type=hikari.TextableGuildChannel,
    channel_types=[hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS],
)
@lightbulb.option("text", "The text to echo.")
@lightbulb.command("echo", "Repeat the provided text as the bot.")
@lightbulb.implements(lightbulb.SlashCommand)
async def echo(ctx: SnedSlashContext) -> None:
    # InteractionChannel has no overrides data
    if ctx.options.channel:
        channel = ctx.app.cache.get_guild_channel(ctx.options.channel.id) or ctx.get_channel()
    else:
        channel = ctx.get_channel()

    perms = lightbulb.utils.permissions_in(channel, ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id))
    if not helpers.includes_permissions(perms, hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL):
        raise lightbulb.BotMissingRequiredPermission(
            perms=hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL
        )

    await channel.send(ctx.options.text)

    embed = hikari.Embed(title="✅ Message sent!", color=ctx.app.embed_green)
    await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@misc.command()
@lightbulb.add_checks(
    lightbulb.bot_has_role_permissions(
        hikari.Permissions.SEND_MESSAGES, hikari.Permissions.READ_MESSAGE_HISTORY, hikari.Permissions.VIEW_CHANNEL
    ),
    lightbulb.has_guild_permissions(hikari.Permissions.MANAGE_MESSAGES),
)
@lightbulb.option("message_link", "You can get this by right-clicking a message.", type=str)
@lightbulb.command("edit", "Edit a message that was sent by the bot.")
@lightbulb.implements(lightbulb.SlashCommand)
async def edit(ctx: SnedSlashContext) -> None:

    message = await helpers.parse_message_link(ctx, ctx.options.message_link)
    if not message:
        return

    channel = ctx.app.cache.get_guild_channel(message.channel_id) or ctx.get_channel()

    perms = lightbulb.utils.permissions_in(channel, ctx.app.cache.get_member(ctx.guild_id, ctx.app.user_id))
    if not helpers.includes_permissions(
        perms,
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY,
    ):
        raise lightbulb.BotMissingRequiredPermission(
            perms=hikari.Permissions.SEND_MESSAGES
            | hikari.Permissions.VIEW_CHANNEL
            | hikari.Permissions.READ_MESSAGE_HISTORY
        )

    if message.author.id != ctx.app.user_id:
        embed = hikari.Embed(
            title="❌ Not Authored",
            description="The bot did not author this message, thus it cannot edit it.",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    modal = miru.Modal(f"Editing message in #{channel.name}")
    modal.add_item(
        miru.TextInput(
            label="Content",
            style=hikari.TextInputStyle.PARAGRAPH,
            placeholder="Type the new content for this message...",
            value=message.content,
            required=True,
            max_length=2000,
        )
    )
    await modal.send(ctx.interaction)
    await modal.wait()
    if not modal.values:
        return

    content = list(modal.values.values())[0]
    await message.edit(content=content)

    embed = hikari.Embed(title="✅ Message edited!", color=ctx.app.embed_green)
    await modal.get_response_context().respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@misc.command()
@lightbulb.add_checks(
    lightbulb.bot_has_role_permissions(
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
    )
)
@lightbulb.command("Raw Content", "Show raw content for this message.")
@lightbulb.implements(lightbulb.MessageCommand)
async def raw(ctx: SnedMessageContext) -> None:
    if ctx.options.target.content:
        await ctx.respond(f"```{ctx.options.target.content}```", flags=hikari.MessageFlag.EPHEMERAL)
    else:
        embed = hikari.Embed(
            title="❌ Missing Content",
            description="Oops! It looks like this message has no content to display!",
            color=ctx.app.error_color,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)


@misc.command()
@lightbulb.option("timezone", "The timezone to set as your default. Example: 'Europe/Kiev'", autocomplete=True)
@lightbulb.command("timezone", "Sets your preferred timezone for other time-related commands to use.")
@lightbulb.implements(lightbulb.SlashCommand)
async def set_timezone(ctx: SnedSlashContext) -> None:
    if ctx.options.timezone not in pytz.common_timezones:
        embed = hikari.Embed(
            title="❌ Invalid Timezone",
            description="Oops! This does not look like a valid timezone! Specify your timezone as a valid `Continent/City` combination.",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)

    await ctx.app.pool.execute(
        """
    INSERT INTO preferences (user_id, timezone) 
    VALUES ($1, $2) 
    ON CONFLICT (user_id) DO 
    UPDATE SET timezone = $2""",
        ctx.user.id,
        ctx.options.timezone,
    )

    embed = hikari.Embed(
        title="✅ Timezone set!",
        description=f"Your preferred timezone has been set to `{ctx.options.timezone}`, all relevant commands will try to adapt to this setting! (E.g. `/reminder`)",
        color=ctx.app.embed_green,
    )
    await ctx.respond(embed=embed)


@set_timezone.autocomplete("timezone")
async def tz_opts(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        return get_close_matches(option.value, pytz.common_timezones, 25)
    return pytz.common_timezones[:25]


@misc.command()
@lightbulb.option(
    "style",
    "Timestamp style.",
    choices=[
        "t - Short time",
        "T - Long time",
        "d - Short date",
        "D - Long Date",
        "f - Short Datetime",
        "F - Long Datetime",
        "R - Relative",
    ],
    required=False,
)
@lightbulb.option("time", "The time to create the timestamp from. Examples: 'in 20 minutes', '2022-04-03', '21:43'")
@lightbulb.command("timestamp", "Create a Discord timestamp from human-readable time formats and dates.")
@lightbulb.implements(lightbulb.SlashCommand)
async def timestamp_gen(ctx: SnedSlashContext) -> None:
    try:
        time = await ctx.app.scheduler.convert_time(ctx.options.time, force_mode="absolute", user=ctx.user)
    except ValueError as error:
        embed = hikari.Embed(
            title="❌ Error: Invalid data entered",
            description=f"Your timeformat is invalid! \n**Error:** {error}",
            color=ctx.app.error_color,
        )
        return await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
    style = ctx.options.style.split(" -")[0] if ctx.options.style else "f"

    await ctx.respond(f"`{helpers.format_dt(time, style=style)}` --> {helpers.format_dt(time, style=style)}")


def load(bot: SnedBot) -> None:
    bot.add_plugin(misc)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(misc)
