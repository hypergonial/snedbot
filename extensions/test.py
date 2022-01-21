import lightbulb
import hikari
import miru

test = lightbulb.Plugin(name="Test")


class MyView(miru.View):
    @miru.button(label="Rock", emoji=chr(129704), style=hikari.ButtonStyle.PRIMARY)
    async def rock_button(self, button: miru.Button, interaction: miru.Interaction):
        await interaction.send_message(content="Paper!")

    @miru.select(placeholder="Select Me!", options=[miru.SelectOption("Option 1"), miru.SelectOption("Option 2")])
    async def test_select(self, select: miru.Select, interaction: miru.Interaction):
        await interaction.send_message(f"you selected {select.values[0]}")

    @miru.button(label="Scissors", emoji=chr(9986), style=hikari.ButtonStyle.PRIMARY)
    async def scissors_button(self, button: miru.Button, interaction: miru.Interaction):
        await interaction.send_message(content="Rock!")

    @miru.button(emoji=chr(9209), style=hikari.ButtonStyle.DANGER)
    async def stop_button(self, button: miru.Button, interaction: miru.Interaction):
        self.stop()  # Stop listening for interactions


@test.command()
@lightbulb.command("test", "Testing views!")
@lightbulb.implements(lightbulb.SlashCommand)
async def test_command(ctx: lightbulb.Context) -> None:

    view = MyView(ctx.app)

    proxy = await ctx.respond("This is a test!", components=view.build())
    view.start((await proxy.message()))
    await view.wait()
    print("View stopped or timed out!")


def load(bot):
    bot.add_plugin(test)


def unload(bot):
    bot.remove_plugin(test)
