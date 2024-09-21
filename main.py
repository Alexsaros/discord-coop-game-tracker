import os
import traceback
import discord
import asyncio
import json
import time
import requests
from discord.ext import commands
from dotenv import load_dotenv
import random


load_dotenv()
APP_ID = os.getenv("APP_ID")
PUBLIC_KEY = os.getenv("PUBLIC_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
STEAM_API_KEY = os.getenv("STEAM_API_KEY")

DATASET_FILE = "dataset.json"

EMBED_MAX_ITEMS = 25
EDIT_GAME_EMBED_COLOR = discord.Color.dark_blue()

EMOJIS = {
    "owned": ":video_game:",
    "not_owned": ":money_with_wings:",
    "1players": ":person_standing:",
    "2players": ":people_holding_hands:",
    "3players": ":family_man_girl_boy:",
    "4players": ":family_mmgb:",
    "free": ":free:",
    "local": ":satellite:",
    "experienced": ":brain:",
    "new": ":new:",
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class CustomHelpCommand(commands.DefaultHelpCommand):

    async def send_bot_help(self, mapping):
        await self.context.message.delete()

        # 20% chance to send a spooky message
        chance_roll = random.randint(1, 5)
        if chance_roll == 1:
            spooky_messages = ["Nobody can help you now...", "Help is near... but so is something else.", "It's too late for help now..."]
            spooky_message = random.choice(spooky_messages)
            channel = self.get_destination()
            message = await channel.send(spooky_message)
            time.sleep(2.5)
            await message.delete()

        # Send the actual help message
        await super().send_bot_help(mapping)


bot = commands.Bot(command_prefix="!", intents=intents, help_command=CustomHelpCommand())


def log(message):
    print(message)
    with open("log.log", "a", encoding="utf-8") as f:
        f.write(message + "\n")


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
    local = False
    played_before = None

    def __init__(self, json_data=None):
        self.votes = {}
        self.tags = []
        self.owned = {}
        self.played_before = {}
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
        self.local = json_data.get("local", False)
        self.played_before = json_data.get("played_before", {})

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
            "local": self.local,
            "played_before": self.played_before,
        }

    def __str__(self):
        return str(self.to_json())


def read_dataset():
    if not os.path.exists(DATASET_FILE):
        log(f"{DATASET_FILE} does not exist. Creating it...")
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
        "overview_channel_id": 0,
        "aliases": {},
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


def get_game_embed_field(game_data, server_dataset):
    """
    Gets the details of the given game from the dataset to be displayed in an embed field.
    Returns a dictionary with keys "name", "value", and "inline", as expected by Discord's embed field.
    """
    description = ""

    if game_data.price_original >= 0:
        price_original = game_data.price_original
        price_current = game_data.price_current

        if price_original == 0:
            price_text = EMOJIS["free"]
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

    if game_data.votes:
        description += "\n> Voted: "
        # Display each voter's alias, falling back to their name if not set
        aliases = server_dataset.get("aliases", {})
        voter_names = []
        voter_aliases = []
        for voter in game_data.votes.keys():
            voter_alias = aliases.get(voter)
            if voter_alias is not None:
                voter_aliases.append(voter_alias)
            else:
                voter_names.append(voter)
        description += " ".join(voter_aliases)
        description += ", ".join(voter_names)

    if game_data.player_count > 0:
        player_count_text = EMOJIS[f"{game_data.player_count}players"]
        description += f"\n> Players: {player_count_text}"

    # Do not display who owns a game if the game is free, as you can't buy a free game
    people_bought_game = (game_data.owned and game_data.price_original != 0)
    if people_bought_game or game_data.local:
        description += "\n> Owned: "

        if people_bought_game:
            # Sums the True/False values, with them corresponding to 1/0
            owned_count = sum(owned for owned in game_data.owned.values())
            description += EMOJIS["owned"] * owned_count
            description += EMOJIS["not_owned"] * (len(game_data.owned) - owned_count)

        if game_data.local:
            description += "(" + EMOJIS["local"] + ")"

    if game_data.played_before:
        description += "\n> Experience: "
        # Sums the True/False values, with them corresponding to 1/0
        played_before_count = sum(played for played in game_data.played_before.values())
        description += EMOJIS["experienced"] * played_before_count
        description += EMOJIS["new"] * (len(game_data.played_before) - played_before_count)

    tags = game_data.tags
    if len(tags) > 0:
        description += "\n> " + "\n> ".join(tags)

    description = description.strip()

    embed_field_info = {
        "name": f"{game_data.id} - {game_data.name}",
        "value": description,
        "inline": False,
    }
    return embed_field_info


def generate_overview_embed(server_id):
    server_id = str(server_id)

    dataset = read_dataset()
    # Try to narrow down the dataset to a specific server
    if server_id not in dataset:
        log(f"Could not find server {server_id} in the dataset.")
        return None
    server_dataset = dataset[server_id]

    sorted_games = sort_games_by_score(server_dataset)
    total_game_count = len(sorted_games)
    # Can only show 25 games at a time
    sorted_games = sorted_games[:EMBED_MAX_ITEMS]

    embed = discord.Embed(title=f"Games overview ({total_game_count} total)", color=discord.Color.blue())
    for game_data, score in sorted_games:
        embed_field_info = get_game_embed_field(game_data, server_dataset)
        embed.add_field(**embed_field_info)

    return embed


async def update_overview(server_id):
    server_id = str(server_id)

    # Get the server dataset
    dataset = read_dataset()
    server_dataset = dataset.get(server_id)
    if server_dataset is None:
        log(f"Could not find server with ID {server_id} in dataset.")
        return

    # Get the Discord server object
    server_object = bot.get_guild(int(server_id))
    if server_object is None:
        log(f"Discord could not find server with ID {server_id}.")
        return

    # Get the channel ID in which the overview message was sent
    overview_channel_id = server_dataset.get("overview_channel_id")
    if overview_channel_id in (None, 0):
        # This server does not have an overview message
        return

    # Get the Discord channel object
    channel_object = server_object.get_channel(overview_channel_id)
    if channel_object is None:
        log(f"Discord could not find channel with ID {overview_channel_id}.")
        return

    # Get the Discord overview message object
    overview_message_id = server_dataset.get("overview_message_id")
    if overview_message_id in (None, 0):
        log(f"Error: overview_message_id not found, but overview_channel_id is present for server {server_id}.")
        return

    overview_message = await channel_object.fetch_message(overview_message_id)

    updated_overview_embed = generate_overview_embed(server_id)
    if updated_overview_embed is not None:
        await overview_message.edit(embed=updated_overview_embed)


async def update_all_overviews():
    dataset = read_dataset()
    for server_id in dataset:
        await update_overview(server_id)


def get_game_price(game_id):
    """
    Uses the Steam API to search for info on the given game ID.
    Returns a dictionary containing the "id", "price_current" and "price_original" keys.
    Returns None if the game wasn't found.
    """
    # Check if an actual game ID was given
    if game_id == 0:
        return None
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
        log(f"Failed to get game with ID \"{game_id}\" using Steam API: {response.status_code}")
        log(response.json())
        return None

    response_json = response.json()
    steam_game_data = response_json.get(game_id, {}).get("data", {})
    if not steam_game_data:
        log(f"Warning: missing Steam info for game ID {game_id}.")
        return None

    game_name = steam_game_data["name"]

    price_current = -1
    price_original = -1
    price_overview = steam_game_data.get("price_overview", {})
    if not price_overview:
        # Sanity check to see if the game is really free
        if not "is_free":
            log(f"Warning: is_free is False, but missing price_overview for game {game_name}.")
        else:
            price_current = 0
            price_original = 0
    else:
        price_currency = price_overview["currency"]
        if price_currency != "EUR":
            log(f"Error: received currency {price_currency} for game {game_name}.")
        else:
            price_current = price_overview["final"] / 100
            price_original = price_overview["initial"] / 100

    steam_info = {
        "id": steam_game_data["steam_appid"],
        "price_current": price_current,
        "price_original": price_original,
    }

    return steam_info


async def update_dataset_steam_prices():
    dataset = read_dataset()
    for server_dataset in dataset.values():
        game_dataset = server_dataset.get("games", {})
        for game_dict in game_dataset.values():
            steam_id = game_dict.get("steam_id", 0)
            steam_game_info = get_game_price(steam_id)
            if steam_game_info is not None:
                game_dict["price_current"] = steam_game_info["price_current"]
                game_dict["price_original"] = steam_game_info["price_original"]

    save_dataset(dataset)

    await update_all_overviews()


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
        log(f"Failed to search for \"{game_name}\" using Steam API: {response.status_code}")
        log(response.json())
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
            log(f"Error: received currency {price_currency} for game {game_name}.")
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
    log(f"\n\n\n{bot.user} has connected to Discord!")
    await update_dataset_steam_prices()
    log("Finished updating Steam prices")


@bot.event
async def on_reaction_add(reaction, user):
    # Ignore the bot's own reactions
    if user == bot.user:
        return
    log(f"{user} added reaction: {reaction.emoji}")

    message = reaction.message
    ctx = await bot.get_context(message)
    # Check if we need to delete the bot's message
    if reaction.emoji == "❌":
        await message.delete()
        return

    if len(message.embeds) == 0:
        return
    # Assume the message only has 1 embed, as multiple aren't possible
    embed = message.embeds[0]
    # Use the embed color to identify the embed's function
    if embed.color == EDIT_GAME_EMBED_COLOR:
        # Split the title into (game_id, game_name)
        if " - " not in embed.title:
            log(f"Error: incorrect game embed title format: \"{embed.title}\".")
            return
        game_id, game_name = embed.title.split(" - ", 1)

        # Get the game's data
        dataset = read_dataset()
        server_id = str(ctx.guild.id)
        server_dataset = dataset[server_id]
        game_data = filter_game_dataset(dataset, server_id, game_name)
        if game_data is None:
            log(f"Could not find game: {str(game_data)}")
            return

        # Try to perform an action based on the added reaction
        try:
            score_emojis = {
                "1️⃣": 1,
                "2️⃣": 2,
                "3️⃣": 3,
                "4️⃣": 4,
                "5️⃣": 5,
                "6️⃣": 6,
                "7️⃣": 7,
                "8️⃣": 8,
                "9️⃣": 9,
                "🔟": 10,
            }
            if reaction.emoji in score_emojis:
                score = score_emojis[reaction.emoji]
                game_data.votes[str(user)] = score
                return

            owned_emojis = {
                "🎮": True,
                "💸": False,
            }
            if reaction.emoji in owned_emojis:
                is_owned = owned_emojis[reaction.emoji]
                game_data.owned[str(user)] = is_owned
                return

            player_count_emojis = {
                "🧍": 1,
                "🧑‍🤝‍🧑": 2,
                "👨‍👧‍👦": 3,
                "👨‍👨‍👧‍👦": 4,
            }
            if reaction.emoji in player_count_emojis:
                player_count = player_count_emojis[reaction.emoji]
                game_data.player_count = player_count
                return

            if reaction.emoji == "📡":
                game_data.local = True
                return

            played_before_emojis = {
                "🧠": True,
                "🆕": False,
            }
            if reaction.emoji in played_before_emojis:
                played_before = played_before_emojis[reaction.emoji]
                game_data.played_before[str(user)] = played_before
                return

        finally:
            # Save the edited game info
            dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
            save_dataset(dataset)

            # Get the updated game info and display it in the embed
            embed_field_info = get_game_embed_field(game_data, server_dataset)
            title = embed_field_info["name"]
            embed_field_info["name"] = ""
            game_embed = discord.Embed(title=title, color=EDIT_GAME_EMBED_COLOR)
            game_embed.add_field(**embed_field_info)

            await message.edit(embed=game_embed)
            await update_overview(server_id)


@bot.command(name="add", help="Adds a new game to the list. Example: !add \"game name\".")
async def add_game(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    try:
        int(game_name)
        await ctx.send("Game name cannot be a number.")
        return
    except ValueError:
        pass

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is not None:
        log(f"Game already added: {str(game_data)}")
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

    await update_overview(server_id)
    await ctx.message.delete()


@bot.command(name="remove", help="Removes a game from the list. Example: !remove \"game name\". "
                                 "It is possible to use the game's ID instead of its name.")
async def remove_game(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game.")
        return

    # Remove the game and save the dataset again without the game
    del dataset[server_id]["games"][str(game_data.id)]
    save_dataset(dataset)

    await update_overview(server_id)
    await ctx.message.delete()


@bot.command(name="vote", help="Sets your preference for playing a game, between 0-10 (including decimals). Example: !vote \"game name\" 7.5. "
                               "It is possible to use the game's ID instead of its name. "
                               "If you haven't voted for a game, your vote will default to 5.")
async def rate_game(ctx, game_name, score):
    log(f"{ctx.author}: {ctx.message.content}")
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
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the vote and save the new game data
    game_data.votes[str(ctx.author)] = score
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_overview(server_id)
    await ctx.message.delete()


@bot.command(name="overview", help="Displays an overview of the most interesting games. Example: !display. "
                                   "Will update the last occurrence of this message when the data gets updated.")
async def overview(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    overview_embed = generate_overview_embed(ctx.guild.id)
    if overview_embed is None:
        await ctx.send("No games registered for this server yet.")
        return

    message = await ctx.send(embed=overview_embed)

    dataset = read_dataset()

    # Store the new message ID
    dataset[server_id]["overview_message_id"] = message.id
    dataset[server_id]["overview_channel_id"] = ctx.channel.id
    save_dataset(dataset)

    await ctx.message.delete()


@bot.command(name="edit", help="Displays the given game as a message to be able edit it using its reactions. Example: !edit \"game name\".")
async def edit(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    server_dataset = dataset[server_id]

    # Get info on the game and display it in an embed
    embed_field_info = get_game_embed_field(game_data, server_dataset)
    title = embed_field_info["name"]
    embed_field_info["name"] = ""
    game_embed = discord.Embed(title=title, color=EDIT_GAME_EMBED_COLOR)
    game_embed.add_field(**embed_field_info)

    await ctx.message.delete()

    message = await ctx.send(embed=game_embed)
    emoji_reactions = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟", "🎮", "💸", "🧍", "🧑‍🤝‍🧑", "👨‍👧‍👦", "👨‍👨‍👧‍👦", "📡", "🧠", "🆕", "❌"]
    for reaction in emoji_reactions:
        await message.add_reaction(reaction)


@bot.command(name="tag", help="Adds an informative tag to a game. Example: !tag \"game name\" \"PvP only\".")
async def tag(ctx, game_name, tag_text):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the tags and save the new game data
    game_data.tags.append(tag_text)
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_overview(server_id)
    await ctx.message.delete()


@bot.command(name="own", help="Sets whether you own a game or not. Example: !own \"game name\" no. "
                              "Anything starting with \"y\" means you own the game, and the opposite for anything starting with \"n\". "
                              "Not entering anything defaults to \"yes\". "
                              "The amount of people that own a game will not be shown if the game is free. "
                              "Not owning a game will automatically mark you as being new to it.")
async def own(ctx, game_name, owns_game="yes"):
    log(f"{ctx.author}: {ctx.message.content}")
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
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the "owned" field and save the new game data
    game_data.owned[str(ctx.author)] = owned
    if not owned:
        game_data.played_before[str(ctx.author)] = False
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_overview(server_id)
    await ctx.message.delete()


@bot.command(name="players", help="Sets with how many players a game can be played, ranging from 1-4. Example: !players \"game name\" 4.")
async def players(ctx, game_name, player_count):
    log(f"{ctx.author}: {ctx.message.content}")
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
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the "player_count" field and save the new game data
    game_data.player_count = player_count
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_overview(server_id)
    await ctx.message.delete()


@bot.command(name="local", help="Sets whether a game can be played locally, requiring only one person to own it. Example: !local \"game name\" no. "
                                "Anything starting with \"y\" means the game is local, and the opposite for anything starting with \"n\". "
                                "Not entering anything defaults to \"yes\".")
async def set_local(ctx, game_name, is_local="yes"):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    if is_local[:1] == "y":
        local = True
    elif is_local[:1] == "n":
        local = False
    else:
        await ctx.send("Received invalid argument.")
        return

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the "local" field and save the new game data
    game_data.local = local
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_overview(server_id)
    await ctx.message.delete()


@bot.command(name="played", help="Sets whether you have played a game before or not. Example: !played \"game name\" no. "
                                 "Anything starting with \"y\" means you've experienced at least a decent part of the game before. "
                                 "Anything starting with \"n\" means you're unfamiliar with the game. "
                                 "Not entering anything defaults to \"yes\".")
async def set_played(ctx, game_name, played_before="yes"):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    if played_before[:1] == "y":
        experienced = True
    elif played_before[:1] == "n":
        experienced = False
    else:
        await ctx.send("Received invalid argument.")
        return

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the "played_before" field and save the new game data
    game_data.played_before[str(ctx.author)] = experienced
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_overview(server_id)
    await ctx.message.delete()


@bot.command(name="steam_id", help="Links a game to a steam ID for the purpose of retrieving prices. Example: !steam_id \"game name\" 105600.")
async def set_steam_id(ctx, game_name, steam_id):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    try:
        steam_id = int(steam_id)
        assert steam_id >= 0
    except (ValueError, AssertionError):
        await ctx.send("Steam ID must be a positive number.")
        return

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the "steam_id" field, retrieve the price again, and save the new game data
    game_data.steam_id = steam_id
    steam_game_info = get_game_price(steam_id)
    # Default to no price if the Steam game couldn't be found
    game_data.price_current = -1
    game_data.price_original = -1
    if steam_game_info is not None:
        game_data.price_current = steam_game_info["price_current"]
        game_data.price_original = steam_game_info["price_original"]
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_overview(server_id)
    await ctx.message.delete()


@bot.command(name="alias", help="Sets an alias for yourself, to be displayed in the overview. Example: !alias :sunglasses:. "
                                "Leave empty to clear your alias.")
async def set_alias(ctx, new_alias=None):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    dataset = read_dataset()
    server_dataset = dataset[server_id]

    # Store the new alias
    aliases = server_dataset.get("aliases", {})
    aliases[str(ctx.author)] = new_alias
    server_dataset["aliases"] = aliases
    save_dataset(dataset)

    await update_overview(server_id)
    await ctx.message.delete()


@bot.command(name="kick", help="Kicks a member from the server. Example: !kick \"member name\".")
async def kick(ctx, member_name):
    log(f"{ctx.author}: {ctx.message.content}")
    member_name = member_name.lower()
    if member_name in ["co-op game tracker", "coop game tracker"]:
        await ctx.send("Ouch! Stop kicking me! :cry:")
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
    with open("err.log", "a", encoding="utf-8") as f:
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
    with open("err.log", "a", encoding="utf-8") as f:
        f.write(f"{timestamp}\n{event}\n{args}\n{kwargs}\n\n")
    raise


# Allows for running multiple threads if needed in the future
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.create_task(bot.start(BOT_TOKEN))
loop.run_forever()
