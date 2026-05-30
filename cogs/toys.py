import random

from discord.ext import commands
from discord import app_commands, Interaction

from database.utils import get_user_by_name
from embeds.affinity import generate_affinity_embed
from libraries.critters.critters import start_critters_game
from services import dice_roller
from services.eight_ball import use_eight_ball
from services.horoscope import create_horoscope_embed
from services.tarot.tarot import create_random_tarot_embed


class Toys(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tarot", description="Draws a major arcana tarot card.")
    async def tarot(self, interaction: Interaction):
        username = str(interaction.user)

        tarot_embed, tarot_file = create_random_tarot_embed(username)

        await interaction.response.send_message(embed=tarot_embed, file=tarot_file)

    @app_commands.command(name="horoscope", description="Divines your daily horoscope.")
    async def horoscope(self, interaction: Interaction):
        username = str(interaction.user)

        horoscope_embed = create_horoscope_embed(username)

        await interaction.response.send_message(embed=horoscope_embed)

    @app_commands.command(name="8ball", description="Use the magic eight ball to answer your yes-or-no question.")
    async def eight_ball(self, interaction: Interaction, question: str = ""):
        answer = use_eight_ball()
        if question:
            answer = f"{str(interaction.user)} asked: {question}\n{answer}"

        await interaction.response.send_message(answer)

    @app_commands.command(name="choose", description="Randomly chooses one of the given options.")
    @app_commands.describe(options="Separate different options with commas. E.g.: red, green, blue.")
    async def choose(self, interaction: Interaction, options: str):
        parsed_options = [option.strip() for option in options.split(",") if option.strip()]

        selected_option = random.choice(parsed_options)
        options_string = ", ".join(parsed_options)
        message_text = f"Possible options: {options_string}.\nChosen: **{selected_option}**."

        await interaction.response.send_message(message_text)

    @app_commands.command(name="roll", description="Performs the given dice rolls and shows the result (e.g. 2d8+3).")
    @app_commands.rename(expression="dice_rolls")
    async def roll_dice(self, interaction: Interaction, expression: str):
        username = str(interaction.user)

        message_text = dice_roller.roll_dice(username, expression)

        await interaction.response.send_message(message_text)

    @app_commands.command(name="critters", description="Start a Critters game against another user or against Cooper (by not giving a username).")
    async def critters(self, interaction: Interaction, username: str = None):
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id

        opponent_user_id = None
        if username is not None:
            opponent_user = get_user_by_name(username)
            if opponent_user.id == user_id:
                await interaction.followup.send("You can't play against yourself!")
                return

            opponent_user_id = opponent_user.id

        await start_critters_game(self.bot, user_id, opponent_user_id)

        await interaction.followup.send("Game started.")

    @app_commands.guild_only()
    @app_commands.command(name="affinity", description="Shows how similarly you vote to other people.")
    async def show_affinity(self, interaction: Interaction):
        server_id = interaction.guild.id
        user_id = interaction.user.id

        affinity_embed = generate_affinity_embed(server_id, user_id)

        await interaction.response.send_message(embed=affinity_embed)
