import arc
import hikari
import miru

from src.config import Config
from src.etc import const
from src.models.client import SnedClient, SnedContext, SnedPlugin

TESTER_STAGING_ROLE = 971843694896513074
TESTER_STAGING_CHANNEL = 971844463884382259
FF_GUILD = 684324252786360476

TEST_NOTICE = """
**You are being contacted in regards to the Falling Frontier Tester Recruitment.**

First of all, congratulations.
As mentioned during the initial application process, we are expanding the test team which is currently focused on core gameplay mechanics and you have been selected to join the current testing group.

Before you can begin testing, you will have to sign an **NDA**, the process of which will be handled by Todd of Stutter Fox Studios and Tim from Hooded Horse.

If you would like to take part and agree to the requirement of signing an NDA, you will be able to coordinate with both Todd and the senior testing team in the `#tester-lounge` once you have received the appropriate roles.

Once the NDA has been signed you will be be given additional permissions, allowing you to go through the setup process for **GitHub** and receive your key through **Steam**.

Should you have any questions regarding the process or testing, feel free to ask in the `#tester-staging` channel after accepting this invitation.

Thank you!

*Notice: This is an automated message, replies will not be read.*
"""

plugin = SnedPlugin("Falling Frontier", default_enabled_guilds=Config().DEBUG_GUILDS or (FF_GUILD, 813803567445049414))


@plugin.listen()
async def hydrate_autoresponse(event: hikari.GuildMessageCreateEvent) -> None:
    if event.guild_id not in (FF_GUILD, 813803567445049414):  # pyright: ignore[reportUnnecessaryContains]
        return

    if event.content and event.content == "Everyone this is your daily reminder to stay hydrated!":
        await event.message.respond("<:FoxHydrate:851099802527072297>")


# TODO: Come back to this after miru templates
@plugin.listen()
async def handle_test_invite(event: hikari.InteractionCreateEvent) -> None:
    if not isinstance(event.interaction, hikari.ComponentInteraction):
        return

    interaction = event.interaction

    if not interaction.custom_id.startswith("FFTEST:") or interaction.guild_id is not None:
        return

    await interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    view = miru.View.from_message(interaction.message)
    for item in view.children:
        item.disabled = True

    await interaction.message.edit(components=view)

    if interaction.custom_id == "FFTEST:ACCEPT":
        await event.app.rest.add_role_to_member(FF_GUILD, interaction.user, TESTER_STAGING_ROLE)
        await interaction.execute(
            embed=hikari.Embed(
                title="Tester Invite Accepted",
                description=f"Please see <#{TESTER_STAGING_CHANNEL}> for further instructions.\n\nThank you for participating!",
                color=const.EMBED_GREEN,
            )
        )
        await event.app.rest.create_message(
            TESTER_STAGING_CHANNEL,
            f"{interaction.user.mention} accepted the testing invitation! Welcome! <:FoxWave:851099801608388628>",
            user_mentions=True,
        )

    elif interaction.custom_id == "FFTEST:DECLINE":
        await interaction.execute(
            embed=hikari.Embed(
                title="Tester Invite Declined",
                description="Thank you for your interest in the Falling Frontier Testing Program.",
                color=const.ERROR_COLOR,
            )
        )
        await event.app.rest.create_message(
            TESTER_STAGING_CHANNEL, f"`{interaction.user.mention}` declined the testing invitation."
        )


@plugin.include
@arc.with_hook(arc.guild_limiter(1800.0, 1))
@arc.slash_command(
    "sendtestnotice", "Send out tester notice to new people.", default_permissions=hikari.Permissions.ADMINISTRATOR
)
async def send_test_notice(
    ctx: SnedContext,
    recipients: arc.Option[
        hikari.Attachment,
        arc.AttachmentParams("A list of all users to send the notice to, one username per line, max 25 users."),
    ],
) -> None:
    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    converter = lightbulb.converters.UserConverter(ctx)
    view = (
        miru.View()
        .add_item(miru.Button(label="Accept", style=hikari.ButtonStyle.SUCCESS, emoji="✔️", custom_id="FFTEST:ACCEPT"))
        .add_item(miru.Button(label="Decline", style=hikari.ButtonStyle.DANGER, emoji="✖️", custom_id="FFTEST:DECLINE"))
    )
    failed = []
    user_str_list = (await recipients.read()).decode("utf-8").splitlines()

    for user_str in user_str_list[:25]:
        try:
            user = await converter.convert(user_str)
            await user.send(TEST_NOTICE, components=view)
        except (hikari.ForbiddenError, hikari.NotFoundError, ValueError, TypeError):
            failed.append(user_str)

    await ctx.respond(
        f"Sent testing notice to **{len(user_str_list) - len(failed)}/{len(user_str_list)}** users.\n\n**Failed to send to:** ```{' '.join(failed) if failed else 'All users were sent the notice.'}```"
    )


@plugin.include
@arc.with_hook(arc.guild_limiter(1800.0, 1))
@arc.slash_command(
    "sendkeys",
    "Send out tester keys to new people.",
    default_permissions=hikari.Permissions.ADMINISTRATOR,
)
async def send_test_key(
    ctx: SnedContext,
    recipients: arc.Option[
        hikari.Attachment,
        arc.AttachmentParams(
            "A list of users to send keys to, one entry per line. Format: username:KEY, max 25 users."
        ),
    ],
) -> None:
    await ctx.respond(hikari.ResponseType.DEFERRED_MESSAGE_CREATE)

    converter = lightbulb.converters.UserConverter(ctx)
    failed = []
    recipients_list = (await recipients.read()).decode("utf-8").splitlines()

    for line in recipients_list[:25]:
        try:
            user_str, key = line.split(":", maxsplit=1)
            user = await converter.convert(user_str.strip())
            await user.send(
                f"Hello!\nYour key for the Falling Frontier Testing Program is: ```{key.strip()}```\nYou may activate it by opening **Steam**, navigating to `Games > Activate a Product on Steam...`, and entering the key."
            )
        except (hikari.ForbiddenError, hikari.NotFoundError, ValueError, TypeError):
            failed.append(line.split(":", maxsplit=1)[0])

    await ctx.respond(
        f"Sent testing keys to **{len(recipients_list) - len(failed)}/{len(recipients_list)}** users.\n\n**Failed to send to:** ```{' '.join(failed) if failed else 'All users were sent their key.'}```"
    )


@arc.loader
def load(bot: SnedClient) -> None:
    bot.add_plugin(plugin)


@arc.unloader
def unload(bot: SnedClient) -> None:
    bot.remove_plugin(plugin)


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
