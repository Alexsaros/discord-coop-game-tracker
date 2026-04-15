from discord.ext import commands

from apis.discord import delete_message
from libraries import codenames
from shared.logger import log


class Games(commands.Cog):

    @commands.command(name="codenames", help="Start a Codenames game.")
    async def start_codenames(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")

        await codenames.create_new_game(ctx)
        await delete_message(ctx.message)

    @commands.command(name="codenames_settings", help="Open the settings menu for Codenames.")
    async def codenames_settings(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")

        await codenames.show_settings(ctx)
        await delete_message(ctx.message)
