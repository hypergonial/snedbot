import hikari
import lightbulb

from models.bot import SnedBot

ff = lightbulb.Plugin("Falling Frontier")
ff.default_enabled_guilds = (684324252786360476, 813803567445049414)


@ff.listener(hikari.GuildMessageCreateEvent)
async def hydrate_autoresponse(event: hikari.GuildMessageCreateEvent) -> None:
    if not event.guild_id or event.guild_id not in (684324252786360476, 813803567445049414):
        return

    if event.content and event.content == "Everyone this is your daily reminder to stay hydrated!":
        await event.message.respond("<:FoxHydrate:851099802527072297>")


def load(bot: SnedBot) -> None:
    bot.add_plugin(ff)


def unload(bot: SnedBot) -> None:
    bot.remove_plugin(ff)
