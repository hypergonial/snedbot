from __future__ import annotations

import typing as t

import hikari
import miru

from src.models.mod_actions import ModerationFlags
from src.models.views import AuthorOnlyView

if t.TYPE_CHECKING:
    import arc

    from src.models.client import SnedContext

__all__ = ("ResponseProvider",)


class ConfirmView(AuthorOnlyView):
    """View that drives the confirm prompt button logic."""

    def __init__(
        self,
        author: hikari.PartialUser | hikari.Snowflakeish,
        *,
        timeout: int,
        confirm_resp: dict[str, t.Any] | None = None,
        cancel_resp: dict[str, t.Any] | None = None,
    ) -> None:
        super().__init__(author, timeout=timeout)
        self.confirm_resp = confirm_resp
        self.cancel_resp = cancel_resp
        self.value: bool | None = None

    @miru.button(emoji="✖️", style=hikari.ButtonStyle.DANGER)
    async def cancel_button(self, ctx: miru.ViewContext, button: miru.Button) -> None:
        self.value = False
        if self.cancel_resp:
            await ctx.edit_response(**self.cancel_resp)
        self.stop()

    @miru.button(emoji="✔️", style=hikari.ButtonStyle.SUCCESS)
    async def confirm_button(self, ctx: miru.ViewContext, button: miru.Button) -> None:
        self.value = True
        if self.confirm_resp:
            await ctx.edit_response(**self.confirm_resp)
        self.stop()


class ResponseProvider:
    """Custom context for use across the bot."""

    def __init__(self, ctx: SnedContext) -> None:
        self.ctx = ctx

    async def confirm(
        self,
        *args: t.Any,
        confirm_payload: dict[str, t.Any] | None = None,
        cancel_payload: dict[str, t.Any] | None = None,
        timeout: int = 120,
        edit: bool = False,
        message: hikari.Message | None = None,
        **kwargs: t.Any,
    ) -> bool | None:
        """Confirm a given action.

        Parameters
        ----------
        ctx : SnedContext
            The context to use for the prompt.
        confirm_payload : dict[str, t.Any] | None, optional
            Optional keyword-only payload to send if the user confirmed, by default None
        cancel_payload : dict[str, t.Any] | None, optional
            Optional keyword-only payload to send if the user cancelled, by default None
        timeout : int, optional
            The default timeout to use for the confirm prompt, by default 120
        edit : bool
            If True, tries editing the initial response or the provided message.
        message : hikari.Message | None, optional
            A message to edit & transform into the confirm prompt if provided, by default None
        *args : Any
            Arguments for the confirm prompt response.
        **kwargs : Any
            Keyword-only arguments for the confirm prompt response.

        Returns
        -------
        bool
            Boolean determining if the user confirmed the action or not.
            None if no response was given before timeout.
        """
        view = ConfirmView(self.ctx.author, timeout=timeout, confirm_resp=confirm_payload, cancel_resp=cancel_payload)

        kwargs.pop("components", None)
        kwargs.pop("component", None)

        if message and edit:
            message = await message.edit(*args, components=view, **kwargs)
        elif edit:
            resp = await self.ctx.edit_initial_response(*args, components=view, **kwargs)
            message = await resp.retrieve_message()
        else:
            resp = await self.ctx.respond(*args, components=view, **kwargs)
            message = await resp.retrieve_message()

        self.ctx.client.miru.start_view(view, bind_to=message)
        await view.wait()
        return view.value

    @t.overload
    async def mod_respond(
        self,
        content: t.Any | hikari.UndefinedType = hikari.UNDEFINED,
        delete_after: int | float | None = None,
        *,
        attachment: hikari.Resourceish | hikari.UndefinedType = hikari.UNDEFINED,
        attachments: t.Sequence[hikari.Resourceish] | hikari.UndefinedType = hikari.UNDEFINED,
        component: hikari.api.ComponentBuilder | hikari.UndefinedType = hikari.UNDEFINED,
        components: t.Sequence[hikari.api.ComponentBuilder] | hikari.UndefinedType = hikari.UNDEFINED,
        embed: hikari.Embed | hikari.UndefinedType = hikari.UNDEFINED,
        embeds: t.Sequence[hikari.Embed] | hikari.UndefinedType = hikari.UNDEFINED,
        tts: bool | hikari.UndefinedType = hikari.UNDEFINED,
        nonce: str | hikari.UndefinedType = hikari.UNDEFINED,
        reply: hikari.Snowflakeish | hikari.PartialMessage | hikari.UndefinedType = hikari.UNDEFINED,
        mentions_everyone: bool | hikari.UndefinedType = hikari.UNDEFINED,
        mentions_reply: bool | hikari.UndefinedType = hikari.UNDEFINED,
        user_mentions: hikari.SnowflakeishSequence[hikari.PartialUser] | bool | hikari.UndefinedType = hikari.UNDEFINED,
        role_mentions: hikari.SnowflakeishSequence[hikari.PartialRole] | bool | hikari.UndefinedType = hikari.UNDEFINED,
    ) -> arc.InteractionResponse: ...

    @t.overload
    async def mod_respond(
        self,
        response_type: hikari.ResponseType,
        content: t.Any | hikari.UndefinedType = hikari.UNDEFINED,
        delete_after: int | float | None = None,
        *,
        attachment: hikari.Resourceish | hikari.UndefinedType = hikari.UNDEFINED,
        attachments: t.Sequence[hikari.Resourceish] | hikari.UndefinedType = hikari.UNDEFINED,
        component: hikari.api.ComponentBuilder | hikari.UndefinedType = hikari.UNDEFINED,
        components: t.Sequence[hikari.api.ComponentBuilder] | hikari.UndefinedType = hikari.UNDEFINED,
        embed: hikari.Embed | hikari.UndefinedType = hikari.UNDEFINED,
        embeds: t.Sequence[hikari.Embed] | hikari.UndefinedType = hikari.UNDEFINED,
        tts: bool | hikari.UndefinedType = hikari.UNDEFINED,
        nonce: str | hikari.UndefinedType = hikari.UNDEFINED,
        reply: hikari.Snowflakeish | hikari.PartialMessage | hikari.UndefinedType = hikari.UNDEFINED,
        mentions_everyone: bool | hikari.UndefinedType = hikari.UNDEFINED,
        mentions_reply: bool | hikari.UndefinedType = hikari.UNDEFINED,
        user_mentions: hikari.SnowflakeishSequence[hikari.PartialUser] | bool | hikari.UndefinedType = hikari.UNDEFINED,
        role_mentions: hikari.SnowflakeishSequence[hikari.PartialRole] | bool | hikari.UndefinedType = hikari.UNDEFINED,
    ) -> arc.InteractionResponse: ...

    async def mod_respond(self, *args: t.Any, **kwargs: t.Any) -> arc.InteractionResponse:
        """Respond to the command while taking into consideration the current moderation command settings.
        This should not be used outside the moderation plugin, and may fail if it is not loaded.
        """
        if self.ctx.guild_id:
            is_ephemeral = bool(
                (await self.ctx.client.mod.get_settings(self.ctx.guild_id)).flags & ModerationFlags.IS_EPHEMERAL
            )
            flags = hikari.MessageFlag.EPHEMERAL if is_ephemeral else hikari.MessageFlag.NONE
        else:
            flags = kwargs.get("flags") or hikari.MessageFlag.NONE

        return await self.ctx.respond(*args, flags=flags, **kwargs)


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
