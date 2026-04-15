import random

from discord.ext import commands
from discord.ext.commands import guild_only

from apis.discord import delete_message
from database.utils import get_user_by_name
from embeds.affinity import generate_affinity_embed
from libraries.critters.critters import start_critters_game
from services import dice_roller
from services.eight_ball import use_eight_ball
from services.horoscope import create_horoscope_embed
from services.tarot.tarot import create_random_tarot_embed
from shared.logger import log


class Toys(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="tarot", help="Draws a major arcana tarot card. Example: !tarot.")
    async def tarot(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")
        username = str(ctx.author)

        tarot_embed, tarot_file = create_random_tarot_embed(username)

        await ctx.send(embed=tarot_embed, file=tarot_file)
        await delete_message(ctx.message)

    @commands.command(name="horoscope", help="Divines your daily horoscope. Example: !horoscope.")
    async def horoscope(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")
        username = str(ctx.author)

        horoscope_embed = create_horoscope_embed(username)

        await ctx.send(embed=horoscope_embed)
        await delete_message(ctx.message)

    @commands.command(name="8ball", help="Use the magic eight ball to answer your yes-or-no question.")
    async def eight_ball(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")

        answer = use_eight_ball()

        await ctx.send(answer)

    @commands.command(name="choose", help="Randomly chooses one of the given options. Example: !choose red green \"light blue\".")
    async def choose(self, ctx, *options):
        log(f"{ctx.author}: {ctx.message.content}")

        selected_option = random.choice(options)
        options_string = ", ".join(options)
        message_text = f"Possible options: {options_string}.\nChosen: **{selected_option}**."
        await ctx.send(message_text)
        await delete_message(ctx.message)

    @commands.command(name="roll", help="Performs the given dice rolls and shows the result. Example: !roll 2d8+3.")
    async def roll_dice(self, ctx, expression):
        log(f"{ctx.author}: {ctx.message.content}")
        username = str(ctx.author)

        message_text = dice_roller.roll_dice(username, expression)

        await ctx.send(message_text)
        await delete_message(ctx.message)

    @commands.command(name="critters", help="Start a Critters game against another user or against Cooper (by not giving a username). Example: !critters alexsaro.")
    async def critters(self, ctx, username: str = None):
        log(f"{ctx.author}: {ctx.message.content}")
        user_id = ctx.author.id

        opponent_user_id = None
        if username is not None:
            opponent_user = get_user_by_name(username)
            if opponent_user.id == user_id:
                await ctx.send("You can't play against yourself!")
                return

            opponent_user_id = opponent_user.id

        await start_critters_game(self.bot, user_id, opponent_user_id)

        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="affinity", help="Shows how similarly you vote to other people. Example: !affinity.")
    async def show_affinity(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id
        user_id = ctx.author.id

        affinity_embed = generate_affinity_embed(server_id, user_id)

        await ctx.send(embed=affinity_embed)
        await delete_message(ctx.message)
