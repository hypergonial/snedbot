import logging
import re
from difflib import get_close_matches

import arc
import hikari
import miru
import psutil
import pytz

from src.etc import const
from src.models.client import SnedClient, SnedContext, SnedPlugin
from src.utils import helpers
from src.utils.scheduler import ConversionMode

logger = logging.getLogger(__name__)

plugin = SnedPlugin("Miscellaneous Commands")
psutil.cpu_percent(interval=1)  # Call so subsequent calls for CPU % will not be blocking

RGB_REGEX = re.compile(r"[0-9]{1,3} [0-9]{1,3} [0-9]{1,3}")


@plugin.include
@arc.slash_command("ping", "Check the bot's latency.")
async def ping(ctx: SnedContext) -> None:
    await ctx.respond(
        embed=hikari.Embed(
            title="🏓 Pong!",
            description=f"Latency: `{round(ctx.client.app.heartbeat_latency * 1000)}ms`",
            color=const.MISC_COLOR,
        )
    )


@plugin.include
@arc.slash_command("embed", "Generates a new embed with the parameters specified")
async def embed(
    ctx: SnedContext,
    title: arc.Option[str, arc.StrParams("The title of the embed. Required.")],
    description: arc.Option[str | None, arc.StrParams("The description of the embed.")] = None,
    footer: arc.Option[str | None, arc.StrParams("The footer of the embed.")] = None,
    thumbnail_url: arc.Option[str | None, arc.StrParams("A URL pointing to an image to use for the thumbnail.")] = None,
    image_url: arc.Option[str | None, arc.StrParams("A URL pointing to an image to use for the embed image.")] = None,
    footer_image_url: arc.Option[
        str | None, arc.StrParams("A URL pointing to an image to use for the embed footer.")
    ] = None,
    author: arc.Option[str | None, arc.StrParams("The author of the embed. Appears above the title.")] = None,
    author_image_url: arc.Option[
        str | None, arc.StrParams("A URL pointing to an image to use for the author's avatar.")
    ] = None,
    author_url: arc.Option[str | None, arc.StrParams("A URL to direct users to if the author is clicked.")] = None,
    color: arc.Option[
        str | None, arc.StrParams("The color of the embed. Expects three space-separated values for an RGB value.")
    ] = None,
    detach: arc.Option[bool, arc.BoolParams("Send the embed in a detached manner from the slash command.")] = False,
) -> None:
    url_options = [
        image_url,
        thumbnail_url,
        footer_image_url,
        author_image_url,
        author_url,
    ]
    for option in url_options:
        if option and not helpers.is_url(option):
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Invalid URL",
                    description="Provided an invalid URL.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

    if color is not None and not RGB_REGEX.fullmatch(color):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid Color",
                description="Colors must be of format `RRR GGG BBB`, three values seperated by spaces.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    embed = (
        hikari.Embed(
            title=title,
            description=description,
            color=color,
        )
        .set_footer(footer, icon=footer_image_url)
        .set_image(image_url)
        .set_thumbnail(thumbnail_url)
        .set_author(
            name=author,
            url=author_url,
            icon=author_image_url,
        )
    )

    if not detach:
        await ctx.respond(embed=embed)
        return

    assert ctx.member is not None

    if ctx.member and not helpers.includes_permissions(ctx.member.permissions, hikari.Permissions.MANAGE_MESSAGES):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Missing Permissions",
                description="Sending embeds detached requires `Manage Messages` permissions!",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    # TODO: shouldn't this be in a hook?
    if ctx.interaction.app_permissions and not helpers.includes_permissions(
        ctx.interaction.app_permissions,
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL,
    ):
        raise arc.BotMissingPermissionsError(
            missing_permissions=hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES
        )

    await ctx.client.rest.create_message(ctx.channel_id, embed=embed)
    await ctx.respond(
        embed=hikari.Embed(title="✅ Embed created!", color=const.EMBED_GREEN), flags=hikari.MessageFlag.EPHEMERAL
    )


@embed.set_error_handler
async def embed_error(ctx: SnedContext, exc: Exception) -> None:
    if isinstance(exc, ValueError):
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Parsing error",
                description=f"An error occurred parsing parameters.\n**Error:** ```{exc}```",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return
    raise exc


@plugin.include
@arc.slash_command("about", "Displays information about the bot.")
async def about(ctx: SnedContext) -> None:
    me = ctx.client.app.get_me()
    assert me is not None
    process = psutil.Process()

    await ctx.respond(
        embed=hikari.Embed(
            title=f"ℹ️ About {me.username}",
            description=f"""**- Made by:** `hypergonial`
**- Servers:** `{len(ctx.client.cache.get_guilds_view())}`
**- Online since:** {helpers.format_dt(ctx.client.start_time, style='R')}
**- Invite:** [Invite me!](https://discord.com/oauth2/authorize?client_id={me.id}&permissions=1494984682710&scope=bot%20applications.commands)
**- Support:** [Click here!](https://discord.gg/KNKr8FPmJa)
**- Terms of Service:** [Click here!](https://github.com/hypergonial/snedbot/blob/main/tos.md)
**- Privacy Policy:** [Click here!](https://github.com/hypergonial/snedbot/blob/main/privacy.md)\n
Blob emoji is licensed under [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0.html)""",
            color=const.EMBED_BLUE,
        )
        .set_thumbnail(me.avatar_url)
        .add_field(
            name="CPU utilization",
            value=f"`{round(psutil.cpu_percent(interval=None))}%`",
            inline=True,
        )
        .add_field(
            name="Memory utilization",
            value=f"`{round(process.memory_info().vms / 1048576)}MB`",
            inline=True,
        )
        .add_field(
            name="Latency",
            value=f"`{round(ctx.client.app.heartbeat_latency * 1000)}ms`",
            inline=True,
        )
    )


@plugin.include
@arc.slash_command("invite", "Invite the bot to your server!")
async def invite(ctx: SnedContext) -> None:
    if not ctx.client.dev_mode:
        invite_url = f"https://discord.com/oauth2/authorize?client_id={ctx.client.user_id}&permissions=1494984682710&scope=applications.commands%20bot"
        await ctx.respond(
            embed=hikari.Embed(
                title="🌟 Yay!",
                description=f"[Click here]({invite_url}) for an invite link!",
                color=const.MISC_COLOR,
            )
        )
    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="🌟 Oops!",
                description="It looks like this bot is in developer mode, and not intended to be invited!",
                color=const.MISC_COLOR,
            )
        )


@plugin.include
@arc.with_hook(arc.guild_limiter(10.0, 1))
@arc.with_hook(arc.bot_has_permissions(perms=hikari.Permissions.CHANGE_NICKNAME))
@arc.slash_command("setnick", "Set the bot's nickname!", default_permissions=hikari.Permissions.MANAGE_NICKNAMES)
async def setnick(
    ctx: SnedContext,
    nickname: arc.Option[
        str | None, arc.StrParams("The nickname to set the bot's nickname to. Type 'None' to reset it!")
    ] = None,
) -> None:
    assert ctx.guild_id is not None

    nickname = nickname[:32] if nickname and nickname.casefold() != "none" else None

    await ctx.client.rest.edit_my_member(
        ctx.guild_id, nickname=nickname, reason=f"Nickname changed via /setnick by {ctx.author}"
    )
    await ctx.respond(
        embed=hikari.Embed(title="✅ Nickname changed!", color=const.EMBED_GREEN), flags=hikari.MessageFlag.EPHEMERAL
    )


@plugin.include
@arc.slash_command("support", "Provides a link to the support Discord.")
async def support(ctx: SnedContext) -> None:
    await ctx.respond("https://discord.gg/KNKr8FPmJa", flags=hikari.MessageFlag.EPHEMERAL)


@plugin.include
@arc.slash_command("source", "Provides a link to the source-code of the bot.")
async def source(ctx: SnedContext) -> None:
    await ctx.respond("<https://github.com/hypergonial/snedbot>")


@plugin.include
@arc.slash_command("serverinfo", "Provides detailed information about this server.")
async def serverinfo(ctx: SnedContext) -> None:
    assert ctx.guild_id is not None
    guild = ctx.client.cache.get_available_guild(ctx.guild_id)
    assert guild is not None

    embed = (
        hikari.Embed(
            title="ℹ️ Server Information",
            description=f"""**- Name:** `{guild.name}`
**- ID:** `{guild.id}`
**- Owner:** `{ctx.client.cache.get_member(guild.id, guild.owner_id)}` (`{guild.owner_id}`)
**- Created at:** {helpers.format_dt(guild.created_at)} ({helpers.format_dt(guild.created_at, style="R")})
**- Member count:** `{guild.member_count}`
**- Roles:** `{len(guild.get_roles())}`
**- Channels:** `{len(guild.get_channels())}`
**- Nitro Boost level:** `{guild.premium_tier}`
**- Nitro Boost count:** `{guild.premium_subscription_count or '*Not found*'}`
**- Preferred locale:** `{guild.preferred_locale}`
**- Community:** `{"Yes" if "COMMUNITY" in guild.features else "No"}`
**- Partner:** `{"Yes" if "PARTNERED" in guild.features else "No"}`
**- Verified:** `{"Yes" if "VERIFIED" in guild.features else "No"}`
**- Discoverable:** `{"Yes" if "DISCOVERABLE" in guild.features else "No"}`
{f"**- Vanity URL:** {guild.vanity_url_code}" if guild.vanity_url_code else ""}
""",
            color=const.EMBED_BLUE,
        )
        .set_thumbnail(guild.icon_url)
        .set_image(guild.banner_url)
    )

    await ctx.respond(embed=embed)


@plugin.include
@arc.with_hook(
    arc.bot_has_permissions(hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL),
)
@arc.slash_command(
    "echo",
    "Repeat the provided text as the bot.",
    default_permissions=hikari.Permissions.MANAGE_MESSAGES,
)
async def echo(ctx: SnedContext, text: arc.Option[str, arc.StrParams("The text to echo.", max_length=2000)]) -> None:
    await ctx.client.rest.create_message(ctx.channel_id, text)

    await ctx.respond(
        embed=hikari.Embed(title="✅ Message sent!", color=const.EMBED_GREEN), flags=hikari.MessageFlag.EPHEMERAL
    )


@plugin.include
@arc.with_hook(
    arc.bot_has_permissions(
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.READ_MESSAGE_HISTORY | hikari.Permissions.VIEW_CHANNEL
    ),
)
@arc.slash_command(
    "edit", "Edit a message that was sent by the bot.", default_permissions=hikari.Permissions.MANAGE_MESSAGES
)
async def edit(
    ctx: SnedContext, message_link: arc.Option[str, arc.StrParams("You can get this by right-clicking a message.")]
) -> None:
    message = await helpers.parse_message_link(ctx, message_link)
    if not message:
        return

    assert ctx.interaction.app_permissions is not None

    channel = ctx.app.cache.get_guild_channel(message.channel_id) or await ctx.app.rest.fetch_channel(
        message.channel_id
    )

    if not helpers.includes_permissions(
        ctx.interaction.app_permissions,
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY,
    ):
        raise lightbulb.BotMissingRequiredPermission(
            perms=hikari.Permissions.SEND_MESSAGES
            | hikari.Permissions.VIEW_CHANNEL
            | hikari.Permissions.READ_MESSAGE_HISTORY
        )

    if message.author.id != ctx.app.user_id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Not Authored",
                description="The bot did not author this message, thus it cannot edit it.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

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
    if not modal.last_context:
        return

    content = next(iter(modal.last_context.values.values()))
    await message.edit(content=content)

    await modal.last_context.respond(
        embed=hikari.Embed(title="✅ Message edited!", color=const.EMBED_GREEN), flags=hikari.MessageFlag.EPHEMERAL
    )


@plugin.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.add_checks(
    bot_has_permissions(
        hikari.Permissions.SEND_MESSAGES | hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
    )
)
@lightbulb.command("Raw Content", "Show raw content for this message.", pass_options=True)
@lightbulb.implements(lightbulb.MessageCommand)
async def raw(ctx: SnedMessageContext, target: hikari.Message) -> None:
    if target.content:
        await ctx.respond(f"```{target.content[:1990]}```", flags=hikari.MessageFlag.EPHEMERAL)
    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Missing Content",
                description="Oops! It looks like this message has no content to display!",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )


@plugin.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
@lightbulb.option("timezone", "The timezone to set as your default. Example: 'Europe/Kiev'", autocomplete=True)
@lightbulb.command(
    "timezone", "Sets your preferred timezone for other time-related commands to use.", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def set_timezone(ctx: SnedSlashContext, timezone: str) -> None:
    if timezone.title() not in pytz.common_timezones:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid Timezone",
                description="Oops! This does not look like a valid timezone! Specify your timezone as a valid `Continent/City` combination.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    await ctx.app.db.execute(
        """
    INSERT INTO preferences (user_id, timezone)
    VALUES ($1, $2)
    ON CONFLICT (user_id) DO
    UPDATE SET timezone = $2""",
        ctx.user.id,
        timezone.title(),
    )
    await ctx.app.db_cache.refresh(table="preferences", user_id=ctx.user.id, timezone=timezone.title())

    await ctx.respond(
        embed=hikari.Embed(
            title="✅ Timezone set!",
            description=f"Your preferred timezone has been set to `{timezone.title()}`, all relevant commands will try to adapt to this setting! (E.g. `/reminder`)",
            color=const.EMBED_GREEN,
        ),
        flags=hikari.MessageFlag.EPHEMERAL,
    )


@set_timezone.autocomplete("timezone")
async def tz_opts(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> list[str]:
    if option.value:
        assert isinstance(option.value, str)
        return get_close_matches(option.value.title(), pytz.common_timezones, 25)
    return []


@plugin.command
@lightbulb.app_command_permissions(None, dm_enabled=False)
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
@lightbulb.command(
    "timestamp", "Create a Discord timestamp from human-readable time formats and dates.", pass_options=True
)
@lightbulb.implements(lightbulb.SlashCommand)
async def timestamp_gen(ctx: SnedSlashContext, time: str, style: str | None = None) -> None:
    try:
        converted_time = await ctx.app.scheduler.convert_time(
            time, conversion_mode=ConversionMode.ABSOLUTE, user=ctx.user
        )
    except ValueError as error:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Error: Invalid data entered",
                description=f"Your timeformat is invalid! \n**Error:** {error}",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return
    style = style.split(" -")[0] if style else "f"

    await ctx.respond(
        f"`{helpers.format_dt(converted_time, style=style)}` --> {helpers.format_dt(converted_time, style=style)}"
    )


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
