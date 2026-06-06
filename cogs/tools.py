import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands

from services import bedtime
from services.free_games import set_user_free_game_notifications
from shared.error_reporter import send_error_message
from shared.logger import log
from shared.utils import reply


class Tools(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.guild_only()
    @app_commands.command(name="kick", description="Kicks a member from the server.")
    @app_commands.describe(member="The member you want to kick.")
    async def kick(self, interaction: discord.Interaction, member: discord.Member):

        if member.name == "Cooper":
            await interaction.response.send_message("Ouch! Stop kicking me! :cry:")
            return

        if member == interaction.user:
            await interaction.response.send_message("Stop hitting yourself.")
            return

        if member.name == "alexsaro":
            await interaction.response.send_message("Don't you try to kick my creator!")
            return

        if member.bot:
            await interaction.response.send_message("You can't kick bots. Pick on your own kind instead.")
            return

        await interaction.response.send_message(f"Hey, <@{member.id}>. <@{interaction.user.id}> just tried to kick you. I'm sorry you had to find out this way.")

    @app_commands.command(name="send_me_free_games", description="Opt in or out of receiving a message when a game is free to keep.")
    @app_commands.rename(notify_on_free_game="enable_notifications")
    @app_commands.describe(notify_on_free_game="Whether to send a notification when a game becomes free to keep.")
    async def send_me_free_games(self, interaction: discord.Interaction, notify_on_free_game: bool = True):
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id

        await set_user_free_game_notifications(self.bot, user_id, notify_on_free_game)

        await interaction.followup.send(f"Set free game notifications to {notify_on_free_game}.")

    @app_commands.guild_only()
    @app_commands.command(name="bedtime", description="Sets a reminder for your bedtime (CET).")
    @app_commands.describe(bedtime_time="24-hour notation of the time to play a reminder at. A negative number disables it.")
    async def set_bedtime(self, interaction: discord.Interaction, bedtime_time: str):
        server_id = interaction.guild.id
        user_id = interaction.user.id

        await bedtime.set_bedtime(self.bot, server_id, user_id, bedtime_time)

        await interaction.response.send_message(f"Set bedtime to {bedtime_time}.", ephemeral=True)

    @commands.is_owner()
    @commands.hybrid_command(name="sync", description="Please don't use.")
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

    @app_commands.command(name="help", description="Shows all commands.")
    async def help(self, interaction: discord.Interaction):
        # 20% chance to send a spooky message
        if random.randint(1, 5) == 1:
            spooky_message = random.choice([
                "Nobody can help you now...",
                "Help is near... but so is something else.",
                "It's too late for help now..."
            ])

            await interaction.response.send_message(spooky_message, ephemeral=True)
            log(f"Sent spooky message: {spooky_message}")
            await asyncio.sleep(2.5)

            await interaction.delete_original_response()

        # Splits messages if they're too big for a single message
        paginator = commands.Paginator(prefix="```", suffix="```")

        commands_by_cog = {}

        for cmd in self.bot.tree.walk_commands():
            # Only look at parent/main commands
            if cmd.parent:
                continue

            category = getattr(cmd, "binding", None)
            category = category.__class__.__name__ if category else "Commands"

            # Add all commands under their category in the dictionary
            commands_by_cog.setdefault(category, []).append(cmd)

        # Create a block of commands for each category
        for category, cmds in commands_by_cog.items():
            paginator.add_line(category)

            # Determine the length of the longest command name in this category
            max_size = max(len(c.name) for c in cmds)

            for cmd in sorted(cmds, key=lambda c: c.name):
                desc = cmd.description or ""
                # Ensure equal spacing between each command and their description
                entry = f"  {cmd.name:<{max_size}} {desc}"

                paginator.add_line(entry)

            # Empty line after each category
            paginator.add_line()

        pages = paginator.pages

        # Send pages
        for page in pages:
            await reply(interaction, page, ephemeral=False)
