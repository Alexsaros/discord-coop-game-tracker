import os
import traceback

import discord
import asyncio
import time
import datetime
from discord.ext import commands
from discord.ext.commands import CommandInvokeError, NoPrivateMessage
from dotenv import load_dotenv
from apscheduler.triggers.cron import CronTrigger

from apis.steam import update_database_steam_prices
from cogs.backlog import Backlog
from cogs.games import Games
from cogs.tools import Tools
from cogs.toys import Toys
from database.backup_service import create_backup
from services.bedtime import load_bedtime_scheduler_jobs
from services.help import CustomHelpCommand
from shared import error_reporter
from libraries import codenames
from shared.exceptions import BotException
from shared.live_messages import update_all_lists, load_list_views
from shared.logger import log
from services.free_games import check_free_to_keep_games
from database.db import db_session_scope, update_db
from database.models.server import Server
from database.models.server_member import ServerMember
from database.models.user import User
from shared.scheduler import get_scheduler
from bot_updater import start_listening_to_updates

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class DiscordBot(commands.Bot):

    async def setup_hook(self):
        try:
            await self.add_cog(Backlog(self))
            await self.add_cog(Tools(self))
            await self.add_cog(Toys(self))
            await self.add_cog(Games())
        except Exception as e:
            await send_error_message(e)


bot = DiscordBot(command_prefix="!", intents=intents, help_command=CustomHelpCommand())


async def send_error_message(exception):
    await error_reporter.send_error_message(bot, exception)


async def update_steam_prices() -> None:
    await update_database_steam_prices()
    await update_all_lists(bot)


@bot.event
async def on_connect():
    log(f"\n\n\n{datetime.datetime.now()}")
    get_scheduler().start()

    # Load scheduled jobs that were saved during earlier runs
    load_bedtime_scheduler_jobs(bot)

    codenames.load_games(bot)

    log("Finished on_connect()")


@bot.event
async def on_ready():
    log(f"{bot.user} has connected to Discord!")

    # Make buttons functional
    await load_list_views(bot)

    # Checks Steam and displays the updated prices
    await update_steam_prices()
    # Check any free-to-keep games
    await check_free_to_keep_games(bot)

    # Create a job to update the prices every 6 hours
    get_scheduler().add_job(update_steam_prices, CronTrigger(hour="0,6,12,18"))
    # Create a job to check for new free-to-keep games every 6 hours
    get_scheduler().add_job(check_free_to_keep_games, CronTrigger(hour="7,19"), args=[bot])
    # Create a job that makes a backup of the dataset every 12 hours
    get_scheduler().add_job(create_backup, CronTrigger(hour="2,14"))
    # Create a job that removes old Codenames games every day
    get_scheduler().add_job(codenames.clean_up_old_games, CronTrigger(hour="18"), args=[bot])

    log("Finished on_ready()")


@bot.event
async def on_reaction_add(reaction, user):
    # Ignore the bot's own reactions
    if user == bot.user:
        return
    message = reaction.message

    # If the reaction is added to a non-bot message, ignore it
    if message.author.name != bot.user.name:
        # Unless I remove someone's message
        if user.name == "alexsaro" and reaction.emoji == "❌":
            await message.delete()
            return
        # Or someone tried to remove my message
        if message.author.name == "alexsaro" and reaction.emoji == "❌":
            message.add_reaction("😏")
        return
    log(f"{user} added reaction {reaction.emoji} to bot's message")

    # Check if we need to delete the bot's message
    if reaction.emoji == "❌":
        await message.delete()


@bot.event
async def on_command_error(ctx, error):
    # If this was an intended exception, just send the exception message to the channel
    if isinstance(error, CommandInvokeError):
        if isinstance(error.original, BotException):
            log(error.original.message)
            await ctx.send(error.original.message)
            return

    # Check if the user tried to use a server command in a DM channel
    if isinstance(error, NoPrivateMessage):
        await ctx.send("This command can only be used in a server.")
        return

    log("\nEncountered command error:")
    log(error)
    log(type(error))
    await ctx.send(error)
    timestamp = time.time()
    with open("err.log", "a", encoding="utf-8") as f:
        f.write(f"{timestamp}\n{error}\n{traceback.format_exception(error)}\n\n")
    traceback.print_exception(error)
    await send_error_message(error)
    raise


@bot.event
async def on_error(event, *args, **kwargs):
    if event == "on_command_error":
        return
    log(f"\nEncountered error in {event}:")
    log(f"args: {args}, kwargs: {kwargs}")

    error_traceback = traceback.format_exc()
    log(error_traceback)

    timestamp = time.time()
    with open("err.log", "a", encoding="utf-8") as f:
        f.write(f"{timestamp}\n{event}\n{args}\n{kwargs}\n{error_traceback}\n\n")

    await send_error_message(error_traceback)
    raise


@bot.before_invoke
async def update_db_hook(ctx):
    if ctx.guild is None:
        return

    with db_session_scope() as db_session:
        # Ensure this server is known in the database
        server_id = ctx.guild.id
        server = db_session.get(Server, server_id)
        if server is None:
            server = Server(id=server_id)
            db_session.add(server)

        # Don't save anything about this user if they are a bot
        if ctx.author.bot:
            return

        # Ensure there is a database entry for this user
        user_id = ctx.author.id
        user = db_session.get(User, user_id)
        if user is None:
            user = User(
                id=user_id,
                username=ctx.author.name,
                global_name=ctx.author.global_name
            )
            db_session.add(user)
        elif user.username != ctx.author.name or \
                user.global_name != ctx.author.global_name:
            # The user has updated their name
            user.username = ctx.author.name
            user.global_name = ctx.author.global_name

        # Ensure this user has a database entry for this server
        member = db_session.get(ServerMember, (user_id, server_id))
        if not member:
            member = ServerMember(
                user_id=user_id,
                server_id=server_id
            )
            db_session.add(member)


if __name__ == "__main__":
    start_listening_to_updates(bot)
    update_db()

    # Allows for running multiple threads if needed in the future
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(bot.start(BOT_TOKEN))
    loop.run_forever()
