import random

from discord.ext import commands
from discord.ext.commands import guild_only

from apis.discord import delete_message
from services import bedtime
from services.free_games import set_user_free_game_notifications
from shared.logger import log
from shared.utils import parse_boolean


class Tools(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @guild_only()
    @commands.command(name="kick", help="Kicks a member from the server. Example: !kick \"member name\".")
    async def kick(self, ctx, member_name):
        log(f"{ctx.author}: {ctx.message.content}")
        member_name = member_name.lower()
        if member_name in ["cooper", "cooper#0487"]:
            await ctx.send("Ouch! Stop kicking me! :cry:")
            return

        if member_name == str(ctx.author):
            await ctx.send("Stop hitting yourself.")
            return

        if member_name in ["alexsaro"]:
            await ctx.send("Don't you try to kick my creator!")
            return

        member_names = [member.name for member in ctx.guild.members if not member.bot]
        if member_name not in member_names:
            await ctx.send(f"Could not find member \"{member_name}\".")
            return

        for member in ctx.guild.members:
            if member_name == member.name:
                member_id = member.id
                await ctx.send(f"Hey, <@{member_id}>. <@{ctx.author.id}> just tried to kick you. I'm sorry you had to find out this way.")
                return

    @guild_only()
    @commands.command(name="view")
    async def view(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")
        username = str(ctx.author)

        if username == "jo.bear":
            view_messages_jo = [
                "Really, Jo? Again?",
                "C'mon, Jo! It's easy! It's ***!overview*** for a detailed overview of the top games, and ***!list*** for a list of all games!",
                "Are you typing the wrong command on purpose, Jo?",
                "What?! What is it that you want to view, Jo?! ***TELL ME!***",
            ]
            message = random.choice(view_messages_jo)
            await ctx.send(message)
            return

        view_messages = [
            ":unamused:",
            "Try !overview or !list instead.",
            "Stop it.",
        ]
        message = random.choice(view_messages)
        await ctx.send(message)

    @commands.command(name="send_me_free_games", help="Opt in or out of receiving a message when a game is free to keep. Example: !send_me_free_games no. Defaults to \"yes\".")
    async def send_me_free_games(self, ctx, notify_on_free_game="yes"):
        log(f"{ctx.author}: {ctx.message.content}")
        user_id = ctx.author.id

        notify = parse_boolean(notify_on_free_game)
        await set_user_free_game_notifications(self.bot, user_id, notify)

        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="bedtime", help="Sets a reminder for your bedtime (CET). Example: !bedtime 21:30.")
    async def set_bedtime(self, ctx, bedtime_time):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id
        user_id = ctx.author.id

        await bedtime.set_bedtime(self.bot, server_id, user_id, bedtime_time)

        await delete_message(ctx.message)
