from discord import app_commands, Interaction
from discord.ext import commands

from libraries import codenames


class Games(commands.Cog):

    @app_commands.command(name="codenames", description="Start a Codenames game.")
    async def start_codenames(self, interaction: Interaction):
        await codenames.create_new_game(interaction)

    @app_commands.command(name="codenames_settings", description="Open the settings menu for Codenames.")
    async def codenames_settings(self, interaction: Interaction):
        await codenames.show_settings(interaction)
        await interaction.response.send_message(f"Opened the Codenames settings as a private message.", ephemeral=True)
