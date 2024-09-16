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
    tags = None

    def __init__(self, json_data=None):
        self.votes = {}
        self.tags = []
        if json_data:
            self.load_json(json_data)

    def load_json(self, json_data):
        self.id = json_data["id"]
        self.name = json_data["name"]
        self.submitter = json_data["submitter"]
        self.votes = json_data.get("votes", {})
        self.tags = json_data.get("tags", [])

    def to_json(self):
        return {
            "id": self.id,
            "name": self.name,
            "submitter": self.submitter,
            "votes": self.votes,
            "tags": self.tags,
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
        game_id = str(int(game_name))
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


def add_game_to_dataset(dataset: dict, server_id, game_data: GameData, set_game_id=True):
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


def sort_games_by_score(game_dataset):
    member_count = game_dataset["members"]
    game_scores = []

    for game_data in game_dataset.values():
        # Skip metadata (i.e. count, members)
        if isinstance(game_data, int):
            continue

        # Count the score for this game
        total_score = 0
        votes = game_data.get("votes", {})
        for voter, score in votes.items():
            total_score += score
        # Use a score of 5 for the non-voters
        non_voters = member_count - len(votes)
        total_score += non_voters * 5

        game_scores.append((game_data, total_score))

    return sorted(game_scores, key=lambda x: x[1], reverse=True)


def generate_overview_embed(server_id):
    server_id = str(server_id)

    game_dataset_servers = read_dataset()
    # Try to narrow down the dataset to a specific server
    if server_id not in game_dataset_servers:
        return None
    game_dataset = game_dataset_servers[server_id]

    sorted_games = sort_games_by_score(game_dataset)

    embed = discord.Embed(title="Games Overview", color=discord.Color.blue())
    for game_data, score in sorted_games:
        description = ""
        tags = game_data.get("tags", [])
        if len(tags) > 0:
            description += "\n".join(tags)

        embed.add_field(
            name=f"{game_data['id']} - {game_data['name']}",
            value=description,
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
    game_dataset = add_game_to_dataset(game_dataset, server_id, game_data)

    # Set the correct member and game count
    member_count = len([member for member in ctx.guild.members if not member.bot])
    game_dataset[server_id]["members"] = member_count
    game_dataset[server_id]["count"] += 1

    save_dataset(game_dataset)

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="vote", help="Sets your preference for playing a game, between 0-10. Example: !vote \"game name\" 7.5. "
                               "It is possible to use the game's ID instead of its name as well. "
                               "If you haven't voted for a game, your vote will default to 5.")
async def rate_game(ctx, game_name, score):
    server_id = str(ctx.guild.id)

    try:
        score = float(score)
        assert 0 <= score <= 10
    except (ValueError, AssertionError):
        await ctx.send("Score must be a number between 0 and 10.")
        return

    game_dataset = read_dataset()
    game_data = filter_game_dataset(game_dataset, server_id, game_name)
    if game_data is None:
        print(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the vote and save the new game data
    votes = game_data.votes
    votes[str(ctx.author)] = float(score)
    game_dataset[server_id][str(game_data.id)] = game_data.to_json()
    save_dataset(game_dataset)

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

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="tag", help="Adds an informative tag to a game. Example: !tag \"game name\" \"PvP only\".")
async def tag(ctx, game_name, tag_text):
    server_id = str(ctx.guild.id)

    game_dataset = read_dataset()
    game_data = filter_game_dataset(game_dataset, server_id, game_name)
    if game_data is None:
        print(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the tags and save the new game data
    game_data.tags.append(tag_text)
    game_dataset[server_id][str(game_data.id)] = game_data.to_json()
    save_dataset(game_dataset)

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="kick", help="Kicks a member from the server. Example: !kick \"member name\".")
async def kick(ctx, member_name):
    member_name = member_name.lower()
    if member_name in ["co-op game tracker", "coop game tracker"]:
        await ctx.send("I won't kick myself, fool.")
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


'''
TODO:
-command to remove games
-link to Steam API to check prices and sales (every time it starts)
-command to indicate whether a game is already owned or not
-command to indicate whether a game can be played locally (with only one person having to purchase it)
-command to indicate whether you've already played the game before
-command to indicate how many players could play the game
'''
