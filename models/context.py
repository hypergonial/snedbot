from __future__ import annotations

import typing as t

import hikari
import lightbulb
import miru

from models.mod_actions import ModerationFlags

from .views import AuthorOnlyView

__all__ = ["SnedContext", "SnedSlashContext", "SnedMessageContext", "SnedUserContext", "SnedPrefixContext"]

if t.TYPE_CHECKING:
    from .bot import SnedBot


class ConfirmView(AuthorOnlyView):
    """View that drives the confirm prompt button logic."""

    def __init__(
        self,
        lctx: lightbulb.Context,
        timeout: int,
        confirm_resp: t.Optional[t.Dict[str, t.Any]] = None,
        cancel_resp: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> None:
        super().__init__(lctx, timeout=timeout)
        self.confirm_resp = confirm_resp
        self.cancel_resp = cancel_resp
        self.value: t.Optional[bool] = None

    @miru.button(emoji="✖️", style=hikari.ButtonStyle.DANGER)
    async def cancel_button(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        self.value = False
        if self.cancel_resp:
            await ctx.edit_response(**self.cancel_resp)
        self.stop()

    @miru.button(emoji="✔️", style=hikari.ButtonStyle.SUCCESS)
    async def confirm_button(self, button: miru.Button, ctx: miru.ViewContext) -> None:
        self.value = True
        if self.confirm_resp:
            await ctx.edit_response(**self.confirm_resp)
        self.stop()


class SnedContext(lightbulb.Context):
    """Custom context for use across the bot."""

    async def confirm(
        self,
        *args,
        confirm_payload: t.Optional[t.Dict[str, t.Any]] = None,
        cancel_payload: t.Optional[t.Dict[str, t.Any]] = None,
        timeout: int = 120,
        edit: bool = False,
        message: t.Optional[hikari.Message] = None,
        **kwargs,
    ) -> t.Optional[bool]:
        """Confirm a given action.

        Parameters
        ----------
        confirm_payload : Optional[Dict[str, Any]], optional
            Optional keyword-only payload to send if the user confirmed, by default None
        cancel_payload : Optional[Dict[str, Any]], optional
            Optional keyword-only payload to send if the user cancelled, by default None
        edit : bool
            If True, tries editing the initial response or the provided message.
        message : Optional[hikari.Message], optional
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

        view = ConfirmView(self, timeout, confirm_payload, cancel_payload)

        kwargs.pop("components", None)
        kwargs.pop("component", None)

        if message and edit:
            message = await message.edit(*args, components=view, **kwargs)
        elif edit:
            resp = await self.edit_last_response(*args, components=view, **kwargs)
        else:
            resp = await self.respond(*args, components=view, **kwargs)
            message = await resp.message()

        assert message is not None
        await view.start(message)
        await view.wait()
        return view.value

    @t.overload
    async def mod_respond(
        self,
        content: hikari.UndefinedOr[t.Any] = hikari.UNDEFINED,
        delete_after: t.Union[int, float, None] = None,
        *,
        attachment: hikari.UndefinedOr[hikari.Resourceish] = hikari.UNDEFINED,
        attachments: hikari.UndefinedOr[t.Sequence[hikari.Resourceish]] = hikari.UNDEFINED,
        component: hikari.UndefinedOr[hikari.api.ComponentBuilder] = hikari.UNDEFINED,
        components: hikari.UndefinedOr[t.Sequence[hikari.api.ComponentBuilder]] = hikari.UNDEFINED,
        embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED,
        embeds: hikari.UndefinedOr[t.Sequence[hikari.Embed]] = hikari.UNDEFINED,
        tts: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        nonce: hikari.UndefinedOr[str] = hikari.UNDEFINED,
        reply: hikari.UndefinedOr[hikari.SnowflakeishOr[hikari.PartialMessage]] = hikari.UNDEFINED,
        mentions_everyone: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        mentions_reply: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        user_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = hikari.UNDEFINED,
        role_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialRole], bool]
        ] = hikari.UNDEFINED,
    ) -> lightbulb.ResponseProxy:
        ...

    @t.overload
    async def mod_respond(
        self,
        response_type: hikari.ResponseType,
        content: hikari.UndefinedOr[t.Any] = hikari.UNDEFINED,
        delete_after: t.Union[int, float, None] = None,
        *,
        attachment: hikari.UndefinedOr[hikari.Resourceish] = hikari.UNDEFINED,
        attachments: hikari.UndefinedOr[t.Sequence[hikari.Resourceish]] = hikari.UNDEFINED,
        component: hikari.UndefinedOr[hikari.api.ComponentBuilder] = hikari.UNDEFINED,
        components: hikari.UndefinedOr[t.Sequence[hikari.api.ComponentBuilder]] = hikari.UNDEFINED,
        embed: hikari.UndefinedOr[hikari.Embed] = hikari.UNDEFINED,
        embeds: hikari.UndefinedOr[t.Sequence[hikari.Embed]] = hikari.UNDEFINED,
        tts: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        nonce: hikari.UndefinedOr[str] = hikari.UNDEFINED,
        reply: hikari.UndefinedOr[hikari.SnowflakeishOr[hikari.PartialMessage]] = hikari.UNDEFINED,
        mentions_everyone: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        mentions_reply: hikari.UndefinedOr[bool] = hikari.UNDEFINED,
        user_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialUser], bool]
        ] = hikari.UNDEFINED,
        role_mentions: hikari.UndefinedOr[
            t.Union[hikari.SnowflakeishSequence[hikari.PartialRole], bool]
        ] = hikari.UNDEFINED,
    ) -> lightbulb.ResponseProxy:
        ...

    async def mod_respond(self, *args, **kwargs) -> lightbulb.ResponseProxy:
        """Respond to the command while taking into consideration the current moderation command settings.
        This should not be used outside the moderation plugin, and may fail if it is not loaded."""

        if self.guild_id:
            is_ephemeral = bool((await self.app.mod.get_settings(self.guild_id)).flags & ModerationFlags.IS_EPHEMERAL)
            flags = hikari.MessageFlag.EPHEMERAL if is_ephemeral else hikari.MessageFlag.NONE
        else:
            flags = kwargs.get("flags") or hikari.MessageFlag.NONE

        return await self.respond(*args, flags=flags, **kwargs)

    @property
    def app(self) -> SnedBot:
        return super().app  # type: ignore

    @property
    def bot(self) -> SnedBot:
        return super().bot  # type: ignore


class SnedApplicationContext(SnedContext, lightbulb.ApplicationContext):
    """Custom ApplicationContext for Sned."""


class SnedSlashContext(SnedApplicationContext, lightbulb.SlashContext):
    """Custom SlashContext for Sned."""


class SnedUserContext(SnedApplicationContext, lightbulb.UserContext):
    """Custom UserContext for Sned."""


class SnedMessageContext(SnedApplicationContext, lightbulb.MessageContext):
    """Custom MessageContext for Sned."""


class SnedPrefixContext(SnedContext, lightbulb.PrefixContext):
    """Custom PrefixContext for Sned."""


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
