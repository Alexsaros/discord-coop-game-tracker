import discord
from discord import app_commands
from discord.ext import commands

from services import bedtime
from services.free_games import set_user_free_game_notifications
from shared.error_reporter import send_error_message
from shared.utils import parse_boolean


class Tools(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.guild_only()
    @app_commands.command(name="kick", description="Kicks a member from the server.")
    async def kick(self, interaction: discord.Interaction, member_name: str):
        member_name = member_name.lower()

        if member_name in ["cooper", "cooper#0487"]:
            await interaction.response.send_message("Ouch! Stop kicking me! :cry:")
            return

        if member_name == str(interaction.user):
            await interaction.response.send_message("Stop hitting yourself.")
            return

        if member_name in ["alexsaro"]:
            await interaction.response.send_message("Don't you try to kick my creator!")
            return

        member_names = [member.name for member in interaction.guild.members if not member.bot]
        if member_name not in member_names:
            await interaction.response.send_message(f"Could not find member \"{member_name}\".")
            return

        for member in interaction.guild.members:
            if member_name == member.name:
                member_id = member.id
                await interaction.response.send_message(f"Hey, <@{member_id}>. <@{interaction.user.id}> just tried to kick you. I'm sorry you had to find out this way.")
                return

    @app_commands.command(name="send_me_free_games", description="Opt in or out of receiving a message when a game is free to keep.")
    async def send_me_free_games(self, interaction: discord.Interaction, notify_on_free_game: str = "yes"):
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id

        notify = parse_boolean(notify_on_free_game)
        await set_user_free_game_notifications(self.bot, user_id, notify)

        await interaction.followup.send(f"Set free game notifications to {notify}.")

    @app_commands.guild_only()
    @app_commands.command(name="bedtime", description="Sets a reminder for your bedtime (CET).")
    async def set_bedtime(self, interaction: discord.Interaction, bedtime_time: str):
        server_id = interaction.guild.id
        user_id = interaction.user.id

        await bedtime.set_bedtime(self.bot, server_id, user_id, bedtime_time)

        await interaction.response.send_message(f"Set bedtime to {bedtime_time}.", ephemeral=True)

    @commands.is_owner()
    @commands.hybrid_command(name="sync")
    async def sync(self, ctx, globally=False):
        try:
            if globally:
                await self.bot.tree.sync()
                await ctx.send("Synced commands globally.", ephemeral=True)
            else:
                await self.bot.tree.sync(guild=ctx.guild)
                await ctx.send("Synced commands to guild.", ephemeral=True)
        except Exception as e:
            await send_error_message(self.bot, f"Error: failed to sync. {e}")
