import logging
import typing as t
from difflib import get_close_matches
from itertools import chain

import arc
import hikari
import miru
import toolbox

from src.etc import const
from src.models import AuthorOnlyNavigator, Tag
from src.models.client import SnedClient, SnedContext, SnedPlugin
from src.utils import helpers

if t.TYPE_CHECKING:
    from miru.ext import nav

logger = logging.getLogger(__name__)

plugin = SnedPlugin("Tag")


class TagEditorModal(miru.Modal):
    """Modal for creation and editing of tags."""

    def __init__(self, name: str | None = None, content: str | None = None) -> None:
        title = "Create a tag"
        if content:
            title = f"Editing tag {name}"

        super().__init__(title, timeout=600)

        if not content:
            self.add_item(
                miru.TextInput(
                    label="Tag Name",
                    custom_id="name",
                    placeholder="Enter a tag name...",
                    required=True,
                    min_length=3,
                    max_length=100,
                    value=name,
                )
            )
        self.add_item(
            miru.TextInput(
                label="Tag Content",
                custom_id="content",
                style=hikari.TextInputStyle.PARAGRAPH,
                placeholder="Enter tag content, supports markdown formatting...",
                required=True,
                max_length=1500,
                value=content,
            )
        )

        self.tag_name = ""
        self.tag_content = ""

    async def callback(self, ctx: miru.ModalContext) -> None:
        if not ctx.values:
            return

        self.tag_name = ctx.get_value_by_id("name", default="")
        self.tag_content = ctx.get_value_by_id("content")


async def tag_name_ac(data: arc.AutocompleteData[SnedClient, str]) -> list[str]:
    """Autocomplete for tag names."""
    if data.focused_value and data.guild_id:
        return (await Tag.fetch_closest_names(str(data.focused_value), data.guild_id)) or []
    return []


async def tag_owned_name_ac(data: arc.AutocompleteData[SnedClient, str]) -> list[str]:
    """Autocomplete for tag names that the user owns."""
    if data.focused_value and data.guild_id:
        return (await Tag.fetch_closest_owned_names(str(data.focused_value), data.guild_id, data.user.id)) or []
    return []


@plugin.include
@arc.slash_command("tag", "Call a tag and display it's contents.")
async def tag_cmd(
    ctx: SnedContext,
    name: arc.Option[str, arc.StrParams("The name of the tag you want to call.", autocomplete_with=tag_name_ac)],
    ephemeral: arc.Option[bool, arc.BoolParams("If True, sends the tag in a way that only you can see it.")] = False,
) -> None:
    assert ctx.guild_id is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id, add_use=True)

    if not tag:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Unknown tag",
                description="Cannot find tag by that name.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return
    flags = hikari.MessageFlag.EPHEMERAL if ephemeral else hikari.MessageFlag.NONE
    await ctx.respond(content=tag.parse_content(ctx), flags=flags)


tags = plugin.include_slash_group("tags", "All commands for managing tags.")


@tags.include
@arc.slash_subcommand("create", "Create a new tag. Opens a modal to specify the details.")
async def tag_create(ctx: SnedContext) -> None:
    assert ctx.guild_id is not None and ctx.member is not None

    modal = TagEditorModal()
    await ctx.respond_with_builder(modal.build_response(ctx.client.miru))
    ctx.client.miru.start_modal(modal)
    await modal.wait()
    if not modal.last_context:
        return

    mctx = modal.last_context

    tag = await Tag.fetch(modal.tag_name.casefold(), ctx.guild_id)
    if tag:
        await mctx.respond(
            embed=hikari.Embed(
                title="❌ Tag exists",
                description=f"This tag already exists. If the owner of this tag is no longer in the server, you can try doing `/tags claim {modal.tag_name.casefold()}`",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    tag = await Tag.create(
        guild=ctx.guild_id,
        name=modal.tag_name.casefold(),
        owner=ctx.author,
        creator=ctx.author,
        aliases=[],
        content=modal.tag_content,
    )

    await mctx.respond(
        embed=hikari.Embed(
            title="✅ Tag created!",
            description=f"You can now call it with `/tag {tag.name}`",
            color=const.EMBED_GREEN,
        )
    )


@tags.include
@arc.slash_subcommand("info", "Display information about the specified tag.")
async def tag_info(
    ctx: SnedContext,
    name: arc.Option[
        str, arc.StrParams("The name of the tag to get information about.", autocomplete_with=tag_name_ac)
    ],
) -> None:
    assert ctx.guild_id is not None
    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if not tag:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Unknown tag",
                description="Cannot find tag by that name.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    owner = ctx.client.cache.get_member(ctx.guild_id, tag.owner_id) or tag.owner_id
    creator = (
        (ctx.client.cache.get_member(ctx.guild_id, tag.creator_id) or tag.creator_id) if tag.creator_id else "Unknown"
    )
    aliases = ", ".join(tag.aliases) if tag.aliases else None

    embed = hikari.Embed(
        title=f"💬 Tag Info: {tag.name}",
        description=f"**Aliases:** `{aliases}`\n**Tag owner:** `{owner}`\n**Tag creator:** `{creator}`\n**Uses:** `{tag.uses}`",
        color=const.EMBED_BLUE,
    )
    if isinstance(owner, hikari.Member):
        embed.set_author(name=str(owner), icon=owner.display_avatar_url)

    await ctx.respond(embed=embed)


@tags.include
@arc.slash_subcommand("alias", "Adds an alias to a tag you own.")
async def tag_alias(
    ctx: SnedContext,
    name: arc.Option[str, arc.StrParams("The tag to add an alias for.", autocomplete_with=tag_owned_name_ac)],
    alias: arc.Option[str, arc.StrParams("The alias to add to this tag.")],
) -> None:
    assert ctx.guild_id is not None

    alias_tag = await Tag.fetch(alias.casefold(), ctx.guild_id)
    if alias_tag:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Alias taken",
                description="A tag or alias already exists with a same name. Try picking a different alias.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if tag and tag.owner_id == ctx.author.id:
        tag.aliases = tag.aliases if tag.aliases else []

        if alias.casefold() not in tag.aliases and len(tag.aliases) <= 5:
            tag.aliases.append(alias.casefold())

        else:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Too many aliases",
                    description=f"Tag `{tag.name}` can only have up to **5** aliases.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        await tag.update()

        await ctx.respond(
            embed=hikari.Embed(
                title="✅ Alias created",
                description=f"Alias created for tag `{tag.name}`!\nYou can now also call it with `/tag {alias.casefold()}`",
                color=const.EMBED_GREEN,
            )
        )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid tag",
                description="You either do not own this tag or it does not exist.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@tags.include
@arc.slash_subcommand("delalias", "Remove an alias from a tag you own.")
async def tag_delalias(
    ctx: SnedContext,
    name: arc.Option[str, arc.StrParams("The tag to remove the alias from.", autocomplete_with=tag_owned_name_ac)],
    alias: arc.Option[str, arc.StrParams("The name of the alias to remove.")],
) -> None:
    assert ctx.guild_id is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)
    if tag and tag.owner_id == ctx.author.id:
        if tag.aliases and alias.casefold() in tag.aliases:
            tag.aliases.remove(alias.casefold())

        else:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Unknown alias",
                    description=f"Tag `{tag.name}` does not have an alias called `{alias.casefold()}`",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        await tag.update()

        await ctx.respond(
            embed=hikari.Embed(
                title="✅ Alias removed",
                description=f"Alias `{alias.casefold()}` for tag `{tag.name}` has been deleted.",
                color=const.EMBED_GREEN,
            )
        )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid tag",
                description="You either do not own this tag or it does not exist.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@tags.include
@arc.slash_subcommand(
    "transfer",
    "Transfer ownership of a tag to another user, letting them modify or delete it.",
)
async def tag_transfer(
    ctx: SnedContext,
    name: arc.Option[str, arc.StrParams("The name of the tag to transfer.", autocomplete_with=tag_owned_name_ac)],
    receiver: arc.Option[hikari.Member, arc.MemberParams("The user to receive the tag.")],
) -> None:
    assert ctx.guild_id is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if tag and tag.owner_id == ctx.author.id:
        tag.owner_id = receiver.id
        await tag.update()

        await ctx.respond(
            embed=hikari.Embed(
                title="✅ Tag transferred",
                description=f"Tag `{tag.name}`'s ownership was successfully transferred to {receiver.mention}",
                color=const.EMBED_GREEN,
            )
        )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid tag",
                description="You either do not own this tag or it does not exist.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@tags.include
@arc.slash_subcommand(
    "claim",
    "Claim a tag that has been created by a user that has since left the server.",
)
async def tag_claim(
    ctx: SnedContext,
    name: arc.Option[str, arc.StrParams("The name of the tag to claim.", autocomplete_with=tag_name_ac)],
) -> None:
    assert ctx.guild_id is not None and ctx.member is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if tag:
        members = ctx.client.cache.get_members_view_for_guild(ctx.guild_id)
        if tag.owner_id not in members or (
            helpers.includes_permissions(toolbox.calculate_permissions(ctx.member), hikari.Permissions.MANAGE_MESSAGES)
            and tag.owner_id != ctx.member.id
        ):
            tag.owner_id = ctx.author.id
            await tag.update()

            await ctx.respond(
                embed=hikari.Embed(
                    title="✅ Tag claimed",
                    description=f"Tag `{tag.name}` now belongs to you.",
                    color=const.EMBED_GREEN,
                )
            )

        else:
            await ctx.respond(
                embed=hikari.Embed(
                    title="❌ Owner present",
                    description="Tag owner is still in the server. You can only claim tags that have been abandoned.",
                    color=const.ERROR_COLOR,
                ),
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Unknown tag",
                description="Cannot find tag by that name.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@tags.include
@arc.slash_subcommand("edit", "Edit the content of a tag you own.")
async def tag_edit(
    ctx: SnedContext,
    name: arc.Option[str, arc.StrParams("The name of the tag to edit.", autocomplete_with=tag_owned_name_ac)],
) -> None:
    assert ctx.member is not None and ctx.guild_id is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if not tag or tag.owner_id != ctx.author.id:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid tag",
                description="You either do not own this tag or it does not exist.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    modal = TagEditorModal(name=tag.name, content=tag.content)
    await ctx.respond_with_builder(modal.build_response(ctx.client.miru))
    ctx.client.miru.start_modal(modal)

    await modal.wait()
    if not modal.last_context:
        return

    mctx = modal.last_context

    tag.content = modal.tag_content

    await tag.update()

    await mctx.respond(
        embed=hikari.Embed(
            title="✅ Tag edited",
            description=f"Tag `{tag.name}` has been successfully edited.",
            color=const.EMBED_GREEN,
        )
    )


@tags.include
@arc.slash_subcommand("delete", "Delete a tag you own.")
async def tag_delete(
    ctx: SnedContext,
    name: arc.Option[str, arc.StrParams("The name of the tag to delete.", autocomplete_with=tag_owned_name_ac)],
) -> None:
    assert ctx.member is not None and ctx.guild_id is not None

    tag = await Tag.fetch(name.casefold(), ctx.guild_id)

    if tag and (
        (tag.owner_id == ctx.author.id)
        or helpers.includes_permissions(toolbox.calculate_permissions(ctx.member), hikari.Permissions.MANAGE_MESSAGES)
    ):
        await tag.delete()

        await ctx.respond(
            embed=hikari.Embed(
                title="✅ Tag deleted",
                description=f"Tag `{tag.name}` has been deleted.",
                color=const.EMBED_GREEN,
            )
        )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="❌ Invalid tag",
                description="You either do not own this tag or it does not exist.",
                color=const.ERROR_COLOR,
            ),
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return


@tags.include
@arc.slash_subcommand("list", "List all tags this server has.")
async def tag_list(
    ctx: SnedContext,
    owner: arc.Option[hikari.User | None, arc.UserParams("Only show tags that are owned by this user.")] = None,
) -> None:
    assert ctx.member is not None and ctx.guild_id is not None

    tags = await Tag.fetch_all(ctx.guild_id, owner)

    if tags:
        tags_fmt = [f"**#{i + 1}** - `{tag.uses}` uses: `{tag.name}`" for i, tag in enumerate(tags)]
        # Only show 8 tags per page
        tags_pages = [tags_fmt[i * 8 : (i + 1) * 8] for i in range((len(tags_fmt) + 8 - 1) // 8)]

        embeds: list[str | hikari.Embed | t.Sequence[hikari.Embed] | nav.Page] = [
            hikari.Embed(
                title=f"💬 Available tags{f' owned by {owner.username}' if owner else ''}:",
                description="\n".join(contents),
                color=const.EMBED_BLUE,
            )
            for contents in tags_pages
        ]

        navigator = AuthorOnlyNavigator(ctx.author, pages=embeds)
        await ctx.respond_with_builder(await navigator.build_response_async(ctx.client.miru))
        ctx.client.miru.start_view(navigator)

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title=f"💬 Available tags{f' owned by {owner.username}' if owner else ''}:",
                description="No tags found! You can create one via `/tags create`",
                color=const.EMBED_BLUE,
            )
        )


@tags.include
@arc.slash_subcommand("search", "Search for a tag name or alias.")
async def tag_search(
    ctx: SnedContext,
    query: arc.Option[str, arc.StrParams("The tag name or alias to search for.", autocomplete_with=tag_name_ac)],
) -> None:
    assert ctx.member is not None and ctx.guild_id is not None

    tags = await Tag.fetch_all(ctx.guild_id)

    if tags:
        names = [tag.name for tag in tags]
        aliases = [tag.aliases for tag in tags if tag.aliases]
        aliases = list(chain(*aliases))

        response = [name for name in get_close_matches(query.casefold(), names)]
        response += [f"*{alias}*" for alias in get_close_matches(query.casefold(), aliases)]

        if response:
            await ctx.respond(
                embed=hikari.Embed(title=f"🔎 Search results for '{query}':", description="\n".join(response[:10]))
            )

        else:
            await ctx.respond(
                embed=hikari.Embed(
                    title="Not found",
                    description="Unable to find tags with that name.",
                    color=const.WARN_COLOR,
                )
            )

    else:
        await ctx.respond(
            embed=hikari.Embed(
                title="🔎 Search failed",
                description="There are no tags on this server yet! You can create one via `/tags create`",
                color=const.WARN_COLOR,
            )
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
