import os
import traceback
import discord
import asyncio
import json
import time
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()
APP_ID = os.getenv("APP_ID")
PUBLIC_KEY = os.getenv("PUBLIC_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")

DATASET_FILE = "dataset.json"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


class GameData:

    id = None
    name = ""
    submitter = ""

    def __init__(self, game_id=None, json_data=None):
        if game_id is None and json_data is None:
            raise Exception("Either game_id or json_data is required when creating a GameData object.")

        if game_id:
            self.id = game_id
        if json_data:
            self.load_json(json_data)

    def load_json(self, json_data):
        self.id = json_data["id"]
        self.name = json_data["name"]
        self.submitter = json_data["submitter"]

    def to_json(self):
        return {
            "id": self.id,
            "name": self.name,
            "submitter": self.submitter,
        }

    def __str__(self):
        return str(self.to_json())


def read_dataset():
    if not os.path.exists(DATASET_FILE):
        print(f"{DATASET_FILE} does not exist.")
        dataset = {"count": 0}
    else:
        with open(DATASET_FILE, "r") as file:
            dataset = json.load(file)

    return dataset


def save_dataset(dataset: dict):
    with open(DATASET_FILE, "w") as file:
        print(dataset)
        json.dump(dataset, file, indent=4)


def filter_game_dataset(dataset: dict, server_id, game_name):
    """
    Checks if the given dataset contains the given game, and returns the game's data as a GameData object.
    Returns None if the game was not found.
    """
    # Narrow down the dataset to a specific server
    server_id = str(server_id)
    if server_id not in dataset:
        dataset[server_id] = {}
    dataset = dataset[server_id]

    try:
        # Check if the game was passed as ID
        game_id = int(game_name)
        if game_id in dataset:
            game_data = dataset[game_id]
            return GameData(json_data=game_data)
    except ValueError:
        print(dataset)
        for game_data in dataset.values():
            if game_data["name"] == game_name:
                return GameData(json_data=game_data)
    return None


def set_game_in_dataset(dataset: dict, server_id, game_data: GameData):
    server_id = str(server_id)
    if server_id not in dataset:
        dataset[server_id] = {}

    dataset[server_id][game_data.id] = game_data.to_json()
    return dataset


@bot.event
async def on_ready():
    print(f"{bot.user} has connected to Discord!")


@bot.command(name="add", help="Adds a new game to the list. Example: !add \"game name\".")
async def add_game(ctx, game_name):
    try:
        int(game_name)
        await ctx.send("Game name cannot be a number.")
        return
    except ValueError:
        pass

    game_dataset = read_dataset()
    game_data = filter_game_dataset(game_dataset, ctx.guild.id, game_name)
    if game_data is not None:
        print(f"Game already added: {str(game_data)}")
        await ctx.send("This game has already been added.")
        return

    # Create a JSON for the new game, add it to the server's dataset, and save the dataset
    game_dataset["count"] += 1
    game_data = GameData(game_dataset["count"])
    game_data.name = game_name
    game_data.submitter = str(ctx.author)
    game_dataset = set_game_in_dataset(game_dataset, ctx.guild.id, game_data)
    save_dataset(game_dataset)

    await ctx.message.delete()


@bot.command(name="vote", help="Sets your preference for playing a game, between 0-10. Example: !vote \"game name\" 7.5. "
                               "It is possible to use the game's ID instead of its name as well.")
async def rate_game(ctx, game_name, score):
    print(ctx)


@bot.command(name="overview", help="Displays on overview of the most interesting games. Example: !display. "
                                   "Will update the last occurrence of this message when the data gets updated.")
async def overview(ctx):
    embed = discord.Embed(title="Games Overview")

    game_dataset = read_dataset()
    # Try to narrow down the dataset to a specific server
    server_id = str(ctx.guild.id)
    if server_id not in game_dataset:
        await ctx.send("No games registered for this server yet.")
        return
    game_dataset = game_dataset[server_id]  # type: dict

    for game_data in game_dataset.values():
        embed.add_field(
            name=game_data["name"],
            value=f"",
            inline=False
        )

    await ctx.send(embed=embed)


@bot.event
async def on_command_error(ctx, error):
    print("Encountered command error:")
    print(ctx)
    print(error)
    print(type(error))
    timestamp = time.time()
    with open("err.log", "a") as f:
        f.write(f"{timestamp}\n{ctx}\n{error}\n{traceback.format_exception(error)}\n\n")
    traceback.print_exception(error)
    raise


@bot.event
async def on_error(event, *args, **kwargs):
    if event == "on_command_error":
        return
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
