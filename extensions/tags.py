import logging
import typing as t
from difflib import get_close_matches
from itertools import chain
from typing import List

import hikari
import lightbulb
import miru

from etc import constants as const
from models import AuthorOnlyNavigator
from models import SnedSlashContext
from models import Tag
from models.bot import SnedBot
from utils import TagHandler
from utils import helpers

logger = logging.getLogger(__name__)

tags = lightbulb.Plugin("Tag", include_datastore=True)


class TagEditorModal(miru.Modal):
    """Modal for creation and editing of tags."""

    def __init__(self, name: t.Optional[str] = None, content: t.Optional[str] = None) -> None:
        title = "Create a tag"
        if content:
            title = f"Editing tag {name}"

        super().__init__(title, timeout=600, autodefer=False)

        if not content:
            self.add_item(
                miru.TextInput(
                    label="Tag Name",
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

        for item, value in ctx.values.items():
            assert isinstance(item, miru.TextInput)
            if item.label == "Tag Name":
                self.tag_name = value
            elif item.label == "Tag Content":
                self.tag_content = value


@tags.command
@lightbulb.option("ephemeral", "If True, sends the tag in a way that only you can see it.", type=bool, default=False)
@lightbulb.option("name", "The name of the tag you want to call.", autocomplete=True)
@lightbulb.command("tag", "Call a tag and display it's contents.", pass_options=True)
@lightbulb.implements(lightbulb.SlashCommand)
async def tag_cmd(ctx: SnedSlashContext, name: str, ephemeral: bool = False) -> None:
    tag: Tag = await tags.d.tag_handler.get(name.casefold(), ctx.guild_id, add_use=True)

    if not tag:
        embed = hikari.Embed(
            title="❌ Unknown tag",
            description="Cannot find tag by that name.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return
    flags = hikari.MessageFlag.EPHEMERAL if ephemeral else hikari.MessageFlag.NONE
    await ctx.respond(content=tags.d.tag_handler.parse_tag_content(ctx, tag.content), flags=flags)


@tag_cmd.autocomplete("name")
async def tag_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        return await tags.d.tag_handler.get_closest_name(option.value, interaction.guild_id)
    return []


@tags.command
@lightbulb.command("tags", "All commands for managing tags.")
@lightbulb.implements(lightbulb.SlashCommandGroup)
async def tag_group(ctx: SnedSlashContext) -> None:
    pass


@tag_group.child
@lightbulb.command("create", "Create a new tag. Opens a modal to specify the details.")
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_create(ctx: SnedSlashContext) -> None:

    assert ctx.guild_id is not None and ctx.member is not None

    modal = TagEditorModal()
    await modal.send(ctx.interaction)
    await modal.wait()
    if not modal.values:
        return

    mctx = modal.get_response_context()

    tag: Tag = await tags.d.tag_handler.get(modal.tag_name.casefold(), ctx.guild_id)
    if tag:
        embed = hikari.Embed(
            title="❌ Tag exists",
            description=f"This tag already exists. If the owner of this tag is no longer in the server, you can try doing `/tags claim {modal.tag_name.casefold()}`",
            color=const.ERROR_COLOR,
        )
        await mctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    new_tag = Tag(
        guild_id=hikari.Snowflake(ctx.guild_id),
        name=modal.tag_name.casefold(),
        owner_id=ctx.author.id,
        aliases=None,
        content=modal.tag_content,
    )
    await tags.d.tag_handler.create(new_tag)
    embed = hikari.Embed(
        title="✅ Tag created!",
        description=f"You can now call it with `/tag {modal.tag_name.casefold()}`",
        color=const.EMBED_GREEN,
    )
    await mctx.respond(embed=embed)


@tag_group.child
@lightbulb.option("name", "The name of the tag to get information about.", autocomplete=True)
@lightbulb.command("info", "Display information about the specified tag.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_info(ctx: SnedSlashContext, name: str) -> None:
    assert ctx.guild_id is not None
    tag: Tag = await tags.d.tag_handler.get(name.casefold(), ctx.guild_id)
    if tag:
        owner = ctx.app.cache.get_member(ctx.guild_id, tag.owner_id) or tag.owner_id
        creator = (
            (ctx.app.cache.get_member(ctx.guild_id, tag.creator_id) or tag.creator_id) if tag.creator_id else "Unknown"
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

    else:
        embed = hikari.Embed(
            title="❌ Unknown tag",
            description="Cannot find tag by that name.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return


@tag_info.autocomplete("name")
async def tag_info_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        return await tags.d.tag_handler.get_closest_name(option.value, interaction.guild_id)
    return []


@tag_group.child
@lightbulb.option("alias", "The alias to add to this tag.")
@lightbulb.option("name", "The tag to add an alias for.", autocomplete=True)
@lightbulb.command("alias", "Adds an alias to a tag you own.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_alias(ctx: SnedSlashContext, name: str, alias: str) -> None:
    alias_tag: Tag = await tags.d.tag_handler.get(alias.casefold(), ctx.guild_id)
    if alias_tag:
        embed = hikari.Embed(
            title="❌ Alias taken",
            description=f"A tag or alias already exists with a same name. Try picking a different alias.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    tag: Tag = await tags.d.tag_handler.get(name.casefold(), ctx.guild_id)

    if tag and tag.owner_id == ctx.author.id:
        tag.aliases = tag.aliases if tag.aliases else []

        if alias.casefold() not in tag.aliases and len(tag.aliases) <= 5:
            tag.aliases.append(alias.casefold())

        else:
            embed = hikari.Embed(
                title="❌ Too many aliases",
                description=f"Tag `{tag.name}` can only have up to **5** aliases.",
                color=const.ERROR_COLOR,
            )
            await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
            return

        await tags.d.tag_handler.update(tag)
        embed = hikari.Embed(
            title="✅ Alias created",
            description=f"Alias created for tag `{tag.name}`!\nYou can now call it with `/tag {alias.casefold()}`",
            color=const.EMBED_GREEN,
        )
        await ctx.respond(embed=embed)

    else:
        embed = hikari.Embed(
            title="❌ Invalid tag",
            description="You either do not own this tag or it does not exist.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return


@tag_alias.autocomplete("name")
async def tag_alias_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        return await tags.d.tag_handler.get_closest_owned_name(option.value, interaction.guild_id, interaction.user)
    return []


@tag_group.child
@lightbulb.option("alias", "The name of the alias to remove.")
@lightbulb.option("name", "The tag to remove the alias from.", autocomplete=True)
@lightbulb.command("delalias", "Remove an alias from a tag you own.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_delalias(ctx: SnedSlashContext, name: str, alias: str) -> None:
    tag: Tag = await tags.d.tag_handler.get(name.casefold(), ctx.guild_id)
    if tag and tag.owner_id == ctx.author.id:

        if tag.aliases and alias.casefold() in tag.aliases:
            tag.aliases.remove(alias.casefold())

        else:
            embed = hikari.Embed(
                title="❌ Unknown alias",
                description=f"Tag `{tag.name}` does not have an alias called `{alias.casefold()}`",
                color=const.ERROR_COLOR,
            )
            await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
            return

        await tags.d.tag_handler.update(tag)
        embed = hikari.Embed(
            title="✅ Alias removed",
            description=f"Alias `{alias.casefold()}` for tag `{tag.name}` has been deleted.",
            color=const.EMBED_GREEN,
        )
        await ctx.respond(embed=embed)

    else:
        embed = hikari.Embed(
            title="❌ Invalid tag",
            description="You either do not own this tag or it does not exist.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return


@tag_delalias.autocomplete("name")
async def tag_delalias_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        return await tags.d.tag_handler.get_closest_owned_name(option.value, interaction.guild_id, interaction.user)
    return []


@tag_group.child
@lightbulb.option("receiver", "The user to receive the tag.", type=hikari.Member)
@lightbulb.option("name", "The name of the tag to transfer.", autocomplete=True)
@lightbulb.command(
    "transfer",
    "Transfer ownership of a tag to another user, letting them modify or delete it.",
    pass_options=True,
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_transfer(ctx: SnedSlashContext, name: str, receiver: hikari.Member) -> None:
    helpers.is_member(receiver)

    tag: Tag = await tags.d.tag_handler.get(name.casefold(), ctx.guild_id)

    if tag and tag.owner_id == ctx.author.id:

        tag.owner_id = receiver.id
        await tags.d.tag_handler.update(tag)

        embed = hikari.Embed(
            title="✅ Tag transferred",
            description=f"Tag `{tag.name}`'s ownership was successfully transferred to {receiver.mention}",
            color=const.EMBED_GREEN,
        )
        await ctx.respond(embed=embed)

    else:
        embed = hikari.Embed(
            title="❌ Invalid tag",
            description="You either do not own this tag or it does not exist.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return


@tag_transfer.autocomplete("name")
async def tag_transfer_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        return await tags.d.tag_handler.get_closest_owned_name(option.value, interaction.guild_id, interaction.user)
    return []


@tag_group.child
@lightbulb.option("name", "The name of the tag to claim.", autocomplete=True)
@lightbulb.command(
    "claim",
    "Claim a tag that has been created by a user that has since left the server.",
    pass_options=True,
)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_claim(ctx: SnedSlashContext, name: str) -> None:

    assert ctx.guild_id is not None and ctx.member is not None

    tag: Tag = await tags.d.tag_handler.get(name.casefold(), ctx.guild_id)

    if tag:
        members = ctx.app.cache.get_members_view_for_guild(ctx.guild_id)
        if tag.owner_id not in members.keys() or (
            helpers.includes_permissions(
                lightbulb.utils.permissions_for(ctx.member), hikari.Permissions.MANAGE_MESSAGES
            )
            and tag.owner_id != ctx.member.id
        ):
            tag.owner_id = ctx.author.id
            await tags.d.tag_handler.update(tag)

            embed = hikari.Embed(
                title="✅ Tag claimed",
                description=f"Tag `{tag.name}` now belongs to you.",
                color=const.EMBED_GREEN,
            )
            await ctx.respond(embed=embed)

        else:
            embed = hikari.Embed(
                title="❌ Owner present",
                description="Tag owner is still in the server. You can only claim tags that have been abandoned.",
                color=const.ERROR_COLOR,
            )
            await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
            return

    else:
        embed = hikari.Embed(
            title="❌ Unknown tag",
            description="Cannot find tag by that name.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return


@tag_claim.autocomplete("name")
async def tag_claim_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        return await tags.d.tag_handler.get_closest_name(option.value, interaction.guild_id)
    return []


@tag_group.child
@lightbulb.option("name", "The name of the tag to edit.", autocomplete=True)
@lightbulb.command("edit", "Edit the content of a tag you own.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_edit(ctx: SnedSlashContext, name: str) -> None:

    assert ctx.member is not None

    tag: Tag = await tags.d.tag_handler.get(name.casefold(), ctx.guild_id)

    if not tag or tag.owner_id != ctx.author.id:
        embed = hikari.Embed(
            title="❌ Invalid tag",
            description="You either do not own this tag or it does not exist.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return

    modal = TagEditorModal(name=tag.name, content=tag.content)
    await modal.send(ctx.interaction)
    await modal.wait()
    if not modal.values:
        return

    mctx = modal.get_response_context()

    tag.content = modal.tag_content

    await tags.d.tag_handler.update(tag)

    embed = hikari.Embed(
        title="✅ Tag edited",
        description=f"Tag `{tag.name}` has been successfully edited.",
        color=const.EMBED_GREEN,
    )
    await mctx.respond(embed=embed)


@tag_edit.autocomplete("name")
async def tag_edit_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        return await tags.d.tag_handler.get_closest_owned_name(option.value, interaction.guild_id, interaction.user)
    return []


@tag_group.child
@lightbulb.option("name", "The name of the tag to delete.", autocomplete=True)
@lightbulb.command("delete", "Delete a tag you own.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_delete(ctx: SnedSlashContext, name: str) -> None:

    assert ctx.member is not None

    tag: Tag = await tags.d.tag_handler.get(name.casefold(), ctx.guild_id)

    if tag and (
        (tag.owner_id == ctx.author.id)
        or helpers.includes_permissions(lightbulb.utils.permissions_for(ctx.member), hikari.Permissions.MANAGE_MESSAGES)
    ):

        await tags.d.tag_handler.delete(name.casefold(), ctx.guild_id)
        embed = hikari.Embed(
            title="✅ Tag deleted",
            description=f"Tag `{tag.name}` has been deleted.",
            color=const.EMBED_GREEN,
        )
        await ctx.respond(embed=embed)

    else:
        embed = hikari.Embed(
            title="❌ Invalid tag",
            description="You either do not own this tag or it does not exist.",
            color=const.ERROR_COLOR,
        )
        await ctx.respond(embed=embed, flags=hikari.MessageFlag.EPHEMERAL)
        return


@tag_delete.autocomplete("name")
async def tag_delete_name_ac(
    option: hikari.AutocompleteInteractionOption, interaction: hikari.AutocompleteInteraction
) -> t.List[str]:
    if option.value:
        return await tags.d.tag_handler.get_closest_owned_name(option.value, interaction.guild_id, interaction.user)
    return []


@tag_group.child
@lightbulb.option("owner", "Only show tags that are owned by this user.", type=hikari.User, required=False)
@lightbulb.command("list", "List all tags this server has.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_list(ctx: SnedSlashContext, owner: t.Optional[hikari.User] = None) -> None:
    assert ctx.member is not None
    tags_list: List[Tag] = await tags.d.tag_handler.get_all(ctx.guild_id, owner)

    if tags_list:
        tags_fmt = []
        for i, tag in enumerate(tags_list):
            tags_fmt.append(f"**#{i+1}** - `{tag.uses}` uses: `{tag.name}`")
        # Only show 8 tags per page
        tags_fmt = [tags_fmt[i * 8 : (i + 1) * 8] for i in range((len(tags_fmt) + 8 - 1) // 8)]
        embeds = []
        for contents in tags_fmt:
            embed = hikari.Embed(
                title=f"💬 Available tags{f' owned by {owner.username}' if owner else ''}:",
                description="\n".join(contents),
                color=const.EMBED_BLUE,
            )
            embeds.append(embed)

        navigator = AuthorOnlyNavigator(ctx, pages=embeds)
        await navigator.send(ctx.interaction)

    else:
        embed = hikari.Embed(
            title=f"💬 Available tags{f' owned by {owner.username}' if owner else ''}:",
            description="No tags found! You can create one via `/tags create`",
            color=const.EMBED_BLUE,
        )
        await ctx.respond(embed=embed)


@tag_group.child
@lightbulb.option("query", "The tag name or alias to search for.")
@lightbulb.command("search", "Search for a tag name or alias.", pass_options=True)
@lightbulb.implements(lightbulb.SlashSubCommand)
async def tag_search(ctx: SnedSlashContext, query: str) -> None:

    assert ctx.member is not None

    tags_list = await tags.d.tag_handler.get_all(ctx.guild_id)

    if tags_list:
        names = [tag.name for tag in tags_list]
        aliases = []
        for tag in tags_list:
            if tag.aliases:
                aliases.append(tag.aliases)

        aliases = list(chain(*aliases))

        name_matches = get_close_matches(query.casefold(), names)
        alias_matches = get_close_matches(query.casefold(), aliases)

        response = [name for name in name_matches]
        response += [f"*{alias}*" for alias in alias_matches]

        if response:
            embed = hikari.Embed(title=f"🔎 Search results for '{query}':", description="\n".join(response[:10]))
            await ctx.respond(embed=embed)

        else:
            embed = hikari.Embed(
                title="Not found",
                description="Unable to find tags with that name.",
                color=const.WARN_COLOR,
            )
            await ctx.respond(embed=embed)

    else:
        embed = hikari.Embed(
            title="🔎 Search failed",
            description="There are no tags on this server yet! You can create one via `/tags create`",
            color=const.WARN_COLOR,
        )
        await ctx.respond(embed=embed)


def load(bot: SnedBot) -> None:
    tag_handler = TagHandler(bot)
    bot.add_plugin(tags)
    tags.d.tag_handler = tag_handler


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(tags)
