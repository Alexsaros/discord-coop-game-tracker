import discord


async def reply(interaction: discord.Interaction, message: str, ephemeral: bool = True):
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(message, ephemeral=ephemeral)
