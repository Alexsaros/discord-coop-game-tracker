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
OVERVIEW_FILE = "overview.json"   # Holds the ID of the message displaying the overview for each server

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


class GameData:

    id = -1
    name = ""
    submitter = ""
    votes = None

    def __init__(self, json_data=None):
        self.votes = {}
        if json_data:
            self.load_json(json_data)

    def load_json(self, json_data):
        self.id = json_data["id"]
        self.name = json_data["name"]
        self.submitter = json_data["submitter"]
        self.votes = json_data.get("votes", {})

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
        dataset = {}
    else:
        with open(DATASET_FILE, "r") as file:
            dataset = json.load(file)   # type: dict[str, int, dict]

    return dataset


def save_dataset(dataset: dict):
    with open(DATASET_FILE, "w") as file:
        json.dump(dataset, file, indent=4)


def filter_game_dataset(game_dataset_servers: dict, server_id, game_name):
    """
    Checks if the given dataset contains the given game, and returns the game's data as a GameData object.
    Returns None if the game was not found.
    """
    # Narrow down the dataset to a specific server
    server_id = str(server_id)
    if server_id not in game_dataset_servers:
        game_dataset_servers[server_id] = {
            "count": 0,
            "members": 1,
        }
    dataset = game_dataset_servers[server_id]

    try:
        # Check if the game was passed as ID
        game_id = int(game_name)
        if game_id in dataset:
            game_data = dataset[game_id]
            return GameData(json_data=game_data)
    except ValueError:
        for game_data in dataset.values():
            # Skip metadata (i.e. count, members)
            if isinstance(game_data, int):
                continue

            if game_data["name"] == game_name:
                return GameData(json_data=game_data)
    return None


def set_game_in_dataset(dataset: dict, server_id, game_data: GameData, set_game_id=True):
    server_id = str(server_id)
    if server_id not in dataset:
        dataset[server_id] = {
            "count": 0,
            "members": 1,
        }

    if set_game_id:
        game_data.id = dataset[server_id]["count"] + 1

    dataset[server_id][game_data.id] = game_data.to_json()
    return dataset


def generate_overview_embed(server_id):
    server_id = str(server_id)

    game_dataset_servers = read_dataset()
    # Try to narrow down the dataset to a specific server
    if server_id not in game_dataset_servers:
        return None
    game_dataset = game_dataset_servers[server_id]

    embed = discord.Embed(title="Games Overview")
    for game_data in game_dataset.values():
        # Skip metadata (i.e. count, members)
        if isinstance(game_data, int):
            continue

        embed.add_field(
            name=f"{game_data['id']} - {game_data['name']}",
            value=f"",
            inline=False
        )
    return embed


async def update_overview(ctx):
    server_id = str(ctx.guild.id)

    if not os.path.exists(OVERVIEW_FILE):
        return
    with open(OVERVIEW_FILE, "r") as file:
        overview_messages = json.load(file)

    if server_id not in overview_messages:
        return
    overview_message_id = overview_messages[server_id]
    overview_message = await ctx.fetch_message(overview_message_id)

    updated_overview_embed = generate_overview_embed(server_id)
    await overview_message.edit(embed=updated_overview_embed)


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

    server_id = str(ctx.guild.id)

    game_dataset = read_dataset()
    game_data = filter_game_dataset(game_dataset, server_id, game_name)
    if game_data is not None:
        print(f"Game already added: {str(game_data)}")
        await ctx.send("This game has already been added.")
        return

    # Create a JSON for the new game, add it to the server's dataset, and save the dataset
    game_data = GameData()
    game_data.name = game_name
    game_data.submitter = str(ctx.author)
    game_dataset = set_game_in_dataset(game_dataset, server_id, game_data)

    # Set the correct member and game count
    member_count = len([member for member in ctx.guild.members if not member.bot])
    game_dataset[server_id]["members"] = member_count
    game_dataset[server_id]["count"] += 1

    save_dataset(game_dataset)

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="vote", help="Sets your preference for playing a game, between 0-10. Example: !vote \"game name\" 7.5. "
                               "It is possible to use the game's ID instead of its name as well.")
async def rate_game(ctx, game_name, score):
    try:
        score = float(score)
    except ValueError:
        await ctx.send("Score must be a number.")
        return

    game_dataset = read_dataset()
    game_data = filter_game_dataset(game_dataset, ctx.guild.id, game_name)
    if game_data is None:
        print(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    votes = game_data.votes
    votes[str(ctx.author)] = float(score)

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="overview", help="Displays on overview of the most interesting games. Example: !display. "
                                   "Will update the last occurrence of this message when the data gets updated.")
async def overview(ctx):
    overview_embed = generate_overview_embed(ctx.guild.id)
    if overview_embed is None:
        await ctx.send("No games registered for this server yet.")
        return

    message = await ctx.send(embed=overview_embed)

    # Retrieve the mapping of server IDs to their overview message IDs
    if not os.path.exists(OVERVIEW_FILE):
        print(f"{OVERVIEW_FILE} does not exist.")
        overview_data = {}
    else:
        with open(OVERVIEW_FILE, "r") as file:
            overview_data = json.load(file)   # type: dict[str, int]

    # Store the new message ID
    overview_data[str(ctx.guild.id)] = message.id
    with open(OVERVIEW_FILE, "w") as file:
        json.dump(overview_data, file, indent=4)


@bot.event
async def on_command_error(ctx, error):
    print("\nEncountered command error:")
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
    print("\nEncountered error:")
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
