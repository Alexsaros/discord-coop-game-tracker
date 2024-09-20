import os
import traceback
import discord
import asyncio
import json
import time
import requests
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()
APP_ID = os.getenv("APP_ID")
PUBLIC_KEY = os.getenv("PUBLIC_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
STEAM_API_KEY = os.getenv("STEAM_API_KEY")

DATASET_FILE = "dataset.json"

EMOJIS = {
    "owned": ":video_game:",
    "not_owned": ":money_with_wings:",
    "1players": ":person_standing:",
    "2players": ":people_holding_hands:",
    "3players": ":family_man_girl_boy:",
    "4players": ":family_mmgb:",
}

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
    player_count = 0
    steam_id = 0
    price_current = -1
    price_original = -1

    def __init__(self, json_data=None):
        self.votes = {}
        self.tags = []
        self.owned = {}
        if json_data:
            self.load_json(json_data)

    def load_json(self, json_data):
        self.id = json_data["id"]
        self.name = json_data["name"]
        self.submitter = json_data["submitter"]
        self.votes = json_data.get("votes", {})
        self.tags = json_data.get("tags", [])
        self.owned = json_data.get("owned", {})
        self.player_count = json_data.get("player_count", 0)
        self.steam_id = json_data.get("steam_id", 0)
        self.price_current = json_data.get("price_current", -1)
        self.price_original = json_data.get("price_original", -1)

    def to_json(self):
        return {
            "id": self.id,
            "name": self.name,
            "submitter": self.submitter,
            "votes": self.votes,
            "tags": self.tags,
            "owned": self.owned,
            "player_count": self.player_count,
            "steam_id": self.steam_id,
            "price_current": self.price_current,
            "price_original": self.price_original,
        }

    def __str__(self):
        return str(self.to_json())


def read_dataset():
    if not os.path.exists(DATASET_FILE):
        print(f"{DATASET_FILE} does not exist. Creating it...")
        dataset = {}
    else:
        with open(DATASET_FILE, "r") as file:
            dataset = json.load(file)   # type: dict[str, int, dict]

    return dataset


def save_dataset(dataset: dict):
    with open(DATASET_FILE, "w") as file:
        json.dump(dataset, file, indent=4)


def create_new_server_entry():
    return {
        "game_count": 0,
        "member_count": 1,
        "games": {},
        "overview_message_id": 0,
    }


def filter_game_dataset(dataset: dict, server_id, game_name):
    """
    Checks if the given dataset contains the given game, and returns the game's data as a GameData object.
    Returns None if the game was not found.
    """
    # Narrow down the dataset to a specific server
    server_id = str(server_id)
    if server_id not in dataset:
        dataset[server_id] = create_new_server_entry()
    game_dataset = dataset[server_id]["games"]

    try:
        # Check if the game was passed as ID
        game_id = str(int(game_name))
        if game_id in game_dataset:
            game_data_dict = game_dataset[game_id]
            return GameData(json_data=game_data_dict)
    except ValueError:
        for game_data_dict in game_dataset.values():
            if game_data_dict["name"] == game_name:
                return GameData(json_data=game_data_dict)
    return None


def add_game_to_dataset(dataset: dict, server_id, game_data: GameData, set_game_id=True):
    server_id = str(server_id)
    if server_id not in dataset:
        dataset[server_id] = create_new_server_entry()

    if set_game_id:
        game_data.id = dataset[server_id]["game_count"] + 1
    # Update the game count
    dataset[server_id]["game_count"] += 1

    dataset[server_id]["games"][game_data.id] = game_data.to_json()
    return dataset


def sort_games_by_score(server_dataset):
    member_count = server_dataset["member_count"]
    game_dataset = server_dataset["games"]
    game_scores = []

    for game_data_dict in game_dataset.values():
        game_data = GameData(json_data=game_data_dict)

        # Count the score for this game
        total_score = 0
        votes = game_data.votes
        for voter, score in votes.items():
            total_score += score
        # Use a score of 5 for the non-voters
        non_voters = member_count - len(votes)
        total_score += non_voters * 5

        game_scores.append((game_data, total_score))

    return sorted(game_scores, key=lambda x: x[1], reverse=True)


def generate_overview_embed(server_id):
    server_id = str(server_id)

    dataset = read_dataset()
    # Try to narrow down the dataset to a specific server
    if server_id not in dataset:
        print(f"Could not find server {server_id} in the dataset.")
        return None
    server_dataset = dataset[server_id]

    sorted_games = sort_games_by_score(server_dataset)

    embed = discord.Embed(title="Games Overview", color=discord.Color.blue())
    for game_data, score in sorted_games:
        description = ""

        if game_data.price_original >= 0:
            price_original = game_data.price_original
            price_current = game_data.price_current

            if price_original == 0:
                price_text = "Free"
            else:
                price_text = f"€{price_original:.2f}"
                # Check if the game has a discount
                if price_current != price_original:
                    if price_current == 0:
                        # The game is currently free
                        price_text = f"~~{price_text}~~ **Currently free**"
                    else:
                        discount_percent = int(((price_original - price_current) / price_original) * 100)
                        price_text = f"~~{price_text}~~ **€{price_current:.2f}** (-{discount_percent}%)"

            # If we have the game ID, add a hyperlink on the game's price
            if game_data.steam_id:
                link = f"https://store.steampowered.com/app/{game_data.steam_id}"
                price_text = f"[{price_text}]({link})"

            description += f"\n> Price: {price_text}"

        if game_data.player_count > 0:
            players_emoji = EMOJIS[f"{game_data.player_count}players"]
            description += f"\n> Players: {players_emoji}"

        if game_data.owned:
            description += "\n> Owned: "
            # Sums the True/False values, with them corresponding to 1/0
            owned_count = sum(owned for owned in game_data.owned.values())
            description += EMOJIS["owned"] * owned_count
            description += EMOJIS["not_owned"] * (len(game_data.owned) - owned_count)

        tags = game_data.tags
        if len(tags) > 0:
            description += "\n> " + "\n> ".join(tags)

        description = description.strip()

        embed.add_field(
            name=f"{game_data.id} - {game_data.name}",
            value=description,
            inline=False
        )
    return embed


async def update_overview(ctx):
    server_id = str(ctx.guild.id)

    dataset = read_dataset()

    if server_id not in dataset or \
            "overview_message_id" not in dataset[server_id]:
        return
    overview_message_id = dataset[server_id]["overview_message_id"]
    if overview_message_id == 0:
        return
    overview_message = await ctx.fetch_message(overview_message_id)

    updated_overview_embed = generate_overview_embed(server_id)
    if updated_overview_embed is not None:
        await overview_message.edit(embed=updated_overview_embed)


def get_game_price(game_id):
    """
    Uses the Steam API to search for info on the given game ID.
    Returns a dictionary containing the "id", "price_current" and "price_original" keys.
    Returns None if the game wasn't found.
    """
    game_id = str(game_id)

    # API URL for getting info on a specific Steam game
    url = f"https://store.steampowered.com/api/appdetails?appids={game_id}&cc=eu"

    params = {
        "appids": game_id,
        "cc": "nl",     # Country used for pricing/currency
        "l": "english",
    }
    response = requests.get(url, params=params)

    if response.status_code >= 300:
        print(f"Failed to get game with ID \"{game_id}\" using Steam API: {response.status_code}")
        print(response.json())
        return None

    response_json = response.json()
    steam_game_data = response_json.get(game_id, {}).get("data", {})
    if not steam_game_data:
        print(f"Warning: missing Steam info for game ID {game_id}.")
        return None

    game_name = steam_game_data["name"]

    price_current = -1
    price_original = -1
    price_overview = steam_game_data.get("price_overview", {})
    if not price_overview:
        # Sanity check to see if the game is really free
        if not "is_free":
            print(f"Warning: is_free is False, but missing price_overview for game {game_name}.")
        else:
            price_current = 0
            price_original = 0
    else:
        price_currency = price_overview["currency"]
        if price_currency != "EUR":
            print(f"Error: received currency {price_currency} for game {game_name}.")
        else:
            price_current = price_overview["final"] / 100
            price_original = price_overview["initial"] / 100

    steam_info = {
        "id": steam_game_data["steam_appid"],
        "price_current": price_current,
        "price_original": price_original,
    }

    return steam_info


def search_steam_for_game(game_name):
    """
    Uses the Steam API to search for the given game.
    Returns a dictionary containing the "id", "price_current" and "price_original" keys.
    Returns None if no results were found.
    """
    game_name = game_name.lower()

    # API URL for searching Steam games
    url = "https://store.steampowered.com/api/storesearch/"

    params = {
        "term": game_name,
        "cc": "nl",     # Country used for pricing/currency
        "l": "english",
    }
    response = requests.get(url, params=params)

    if response.status_code >= 300:
        print(f"Failed to search for \"{game_name}\" using Steam API: {response.status_code}")
        print(response.json())
        return None

    response_json = response.json()
    game_results = response_json["items"]
    if len(game_results) == 0:
        return None

    # Check if we find any exact matches. If not, use the first result
    for game in game_results:
        if game["name"].lower() == game_name:
            game_match = game
            break
    else:
        game_match = game_results[0]

    price_current = -1
    price_original = -1
    price_overview = game_match.get("price", {})
    if not price_overview:
        # The game is free
        price_current = 0
        price_original = 0
    else:
        price_currency = price_overview["currency"]
        if price_currency != "EUR":
            game_name = game_match["name"]
            print(f"Error: received currency {price_currency} for game {game_name}.")
        else:
            price_current = price_overview["final"] / 100
            price_original = price_overview["initial"] / 100

    steam_info = {
        "id": game_match["id"],
        "price_current": price_current,
        "price_original": price_original,
    }

    return steam_info


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

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is not None:
        print(f"Game already added: {str(game_data)}")
        await ctx.send("This game has already been added.")
        return

    # Create an object for the new game,
    game_data = GameData()

    # Search Steam for this game and save the info
    steam_game_info = search_steam_for_game(game_name)
    if steam_game_info is not None:
        game_data.steam_id = steam_game_info["id"]
        game_data.price_current = steam_game_info["price_current"]
        game_data.price_original = steam_game_info["price_original"]

    # Add miscellaneous info, add the game to the server's dataset, and save the dataset
    game_data.name = game_name
    game_data.submitter = str(ctx.author)
    dataset = add_game_to_dataset(dataset, server_id, game_data)

    # Set the correct member count
    member_count = len([member for member in ctx.guild.members if not member.bot])
    dataset[server_id]["member_count"] = member_count

    save_dataset(dataset)

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="remove", help="Removes a game from the list. Example: !remove \"game name\". "
                                 "It is possible to use the game's ID instead of its name.")
async def remove_game(ctx, game_name):
    server_id = str(ctx.guild.id)

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        print(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game.")
        return

    # Remove the game and save the dataset again without the game
    del dataset[server_id]["games"][str(game_data.id)]
    save_dataset(dataset)

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="vote", help="Sets your preference for playing a game, between 0-10 (including decimals). Example: !vote \"game name\" 7.5. "
                               "It is possible to use the game's ID instead of its name. "
                               "If you haven't voted for a game, your vote will default to 5.")
async def rate_game(ctx, game_name, score):
    server_id = str(ctx.guild.id)

    try:
        score = float(score)
        assert 0 <= score <= 10
    except (ValueError, AssertionError):
        await ctx.send("Score must be a number between 0 and 10.")
        return

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        print(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the vote and save the new game data
    game_data.votes[str(ctx.author)] = score
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="overview", help="Displays an overview of the most interesting games. Example: !display. "
                                   "Will update the last occurrence of this message when the data gets updated.")
async def overview(ctx):
    overview_embed = generate_overview_embed(ctx.guild.id)
    if overview_embed is None:
        await ctx.send("No games registered for this server yet.")
        return

    message = await ctx.send(embed=overview_embed)

    dataset = read_dataset()

    # Store the new message ID
    dataset[str(ctx.guild.id)]["overview_message_id"] = message.id
    save_dataset(dataset)

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="tag", help="Adds an informative tag to a game. Example: !tag \"game name\" \"PvP only\".")
async def tag(ctx, game_name, tag_text):
    server_id = str(ctx.guild.id)

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        print(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the tags and save the new game data
    game_data.tags.append(tag_text)
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="own", help="Sets whether you own a game or not. Example: !own \"game name\" no. "
                              "Anything starting with \"y\" means you own the game, and the opposite for anything starting with \"n\".")
async def own(ctx, game_name, owns_game):
    server_id = str(ctx.guild.id)

    if owns_game[:1] == "y":
        owned = True
    elif owns_game[:1] == "n":
        owned = False
    else:
        await ctx.send("Received invalid argument.")
        return

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        print(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the "owned" field and save the new game data
    game_data.owned[str(ctx.author)] = owned
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_overview(ctx)
    await ctx.message.delete()


@bot.command(name="players", help="Sets with how many players a game can be played, ranging from 1-4. Example: !players \"game name\" 4.")
async def players(ctx, game_name, player_count):
    server_id = str(ctx.guild.id)

    try:
        player_count = int(player_count)
        assert 1 <= player_count <= 4
    except (ValueError, AssertionError):
        await ctx.send("Player count must be a number between 1 and 4.")
        return

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        print(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the "player_count" field and save the new game data
    game_data.player_count = player_count
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

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
    print(error)
    print(type(error))
    await ctx.send(error)
    timestamp = time.time()
    with open("err.log", "a") as f:
        f.write(f"{timestamp}\n{error}\n{traceback.format_exception(error)}\n\n")
    traceback.print_exception(error)
    raise


@bot.event
async def on_error(event, *args, **kwargs):
    if event == "on_command_error":
        return
    print(f"\nEncountered error in {event}:")
    print(f"args: {args}, kwargs: {kwargs}")
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
-link to Steam API to check prices and sales (every time it starts)
-command to indicate whether a game can be played locally (with only one person having to purchase it)
-command to indicate whether you've already played the game before
-add an "edit" command that shows a temporary message with emojis as functioning as shortcut buttons for commands, when pressing the X emoji, delete the message
-allow users to set an alias (e.g. an emoji) and show the aliases of the people who voted on a game
'''
