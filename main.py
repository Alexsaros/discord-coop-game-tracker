import os
import discord
import asyncio
import time
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()
APP_ID = os.getenv("APP_ID")
PUBLIC_KEY = os.getenv("PUBLIC_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")


@bot.event
async def on_error(event, *args, **kwargs):
    print("Encountered error:")
    print(event)
    print(args)
    print(kwargs)
    timestamp = time.time()
    with open("err.log", "a") as f:
        f.write(f"{timestamp}\n{event}\n{args}\n{kwargs}\n\n")
        raise


# Allows for running multiple threads if needed in the future
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.create_task(bot.start(BOT_TOKEN))
loop.run_forever()
