import os
import traceback
import discord
import asyncio
import json
import time
import requests
import datetime
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
EMBED_MAX_CHARACTERS = 6000
EDIT_GAME_EMBED_COLOR = discord.Color.dark_blue()
OVERVIEW_EMBED_COLOR = discord.Color.blue()
LIST_EMBED_COLOR = discord.Color.blurple()
AFFINITY_EMBED_COLOR = discord.Color.purple()

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
        self.width = 1000   # Allows all command descriptions to be displayed
        self.no_category = "Commands"

        # 20% chance to send a spooky message
        chance_roll = random.randint(1, 5)
        if chance_roll == 1:
            spooky_messages = ["Nobody can help you now...", "Help is near... but so is something else.", "It's too late for help now..."]
            spooky_message = random.choice(spooky_messages)
            channel = self.get_destination()
            message = await channel.send(spooky_message)
            log(f"Sent spooky message: {spooky_message}")
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


class FinishedGameData(GameData):

    finished_timestamp = 0
    enjoyment_scores = None

    def __init__(self, json_data=None):
        self.enjoyment_scores = {}
        super().__init__(json_data=json_data)

    def load_json(self, json_data):
        super().load_json(json_data)
        self.finished_timestamp = json_data.get("finished_timestamp", 0)
        self.enjoyment_scores = json_data.get("enjoyment_scores", {})

    def to_json(self):
        json_data = super().to_json()
        json_data["finished_timestamp"] = self.finished_timestamp
        json_data["enjoyment_scores"] = self.enjoyment_scores
        return json_data


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
        "list_message_id": 0,
        "list_channel_id": 0,
        "hall_of_game_message_id": 0,
        "hall_of_game_channel_id": 0,
        "aliases": {},
        "finished_games": {},
    }


def filter_game_dataset(dataset: dict, server_id, game_name, finished=False):
    """
    Checks if the given dataset contains the given game, and returns the game's data as a GameData object.
    Returns None if the game was not found.
    """
    # Narrow down the dataset to a specific server
    server_id = str(server_id)
    if server_id not in dataset:
        dataset[server_id] = create_new_server_entry()
    if finished:
        game_dataset = dataset[server_id]["finished_games"]
    else:
        game_dataset = dataset[server_id]["games"]

    try:
        # Check if the game was passed as ID
        game_id = str(int(game_name))
        if game_id in game_dataset:
            game_data_dict = game_dataset[game_id]
            if finished:
                return FinishedGameData(json_data=game_data_dict)
            else:
                return GameData(json_data=game_data_dict)
    except ValueError:
        for game_data_dict in game_dataset.values():
            if game_data_dict["name"] == game_name:
                if finished:
                    return FinishedGameData(json_data=game_data_dict)
                else:
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


def sort_games_by_score(server_dataset, finished_games=False):
    member_count = server_dataset["member_count"]
    if finished_games:
        game_dataset = server_dataset.get("finished_games", {})
    else:
        game_dataset = server_dataset.get("games", {})
    game_scores = []

    for game_data_dict in game_dataset.values():
        if finished_games:
            game_data = FinishedGameData(json_data=game_data_dict)
        else:
            game_data = GameData(json_data=game_data_dict)

        # Count the score for this game
        total_score = 0
        if finished_games:
            votes = game_data.enjoyment_scores
        else:
            votes = game_data.votes
        for voter, score in votes.items():
            total_score += score
        # Use a score of 5 for the non-voters
        non_voters = member_count - len(votes)
        total_score += non_voters * 5

        game_scores.append((game_data, total_score))

    return sorted(game_scores, key=lambda x: x[1], reverse=True)


def get_users_aliases_string(server_dataset, users_list):
    # Get each user's alias, falling back to their name if not set
    users_text = ""
    aliases = server_dataset.get("aliases", {})
    user_names = []
    user_aliases = []
    for user in users_list:
        user_alias = aliases.get(user)
        if user_alias is not None:
            user_aliases.append(user_alias)
        else:
            user_names.append(user)
    users_text += " ".join(user_aliases)
    users_text += ", ".join(user_names)
    return users_text


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
        voters = game_data.votes.keys()
        voters_text = get_users_aliases_string(server_dataset, voters)
        description += voters_text

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

    title_text = f"Games overview ({total_game_count} total)"
    total_characters = len(title_text)
    embed = discord.Embed(title=title_text, color=OVERVIEW_EMBED_COLOR)
    for game_data, score in sorted_games:
        embed_field_info = get_game_embed_field(game_data, server_dataset)

        # Check if we have enough characters left in the embed to add the new entry
        total_characters += len(embed_field_info["name"]) + len(embed_field_info["value"])
        if total_characters > EMBED_MAX_CHARACTERS:
            return embed

        embed.add_field(**embed_field_info)

    return embed


def generate_list_embed(server_id):
    server_id = str(server_id)

    dataset = read_dataset()
    # Try to narrow down the dataset to this server
    if server_id not in dataset:
        log(f"Could not find server {server_id} in the dataset.")
        return None

    server_dataset = dataset[server_id]
    sorted_games = sort_games_by_score(server_dataset)

    guild = bot.get_guild(int(server_id))
    if guild is None:
        log(f"Error: could not find server with ID {server_id}.")
        return None

    games_list = []
    for game_data, score in sorted_games:
        # Get everyone who hasn't voted yet
        non_voters = [member.name for member in guild.members if not member.bot]
        for name in game_data.votes.keys():
            try:
                non_voters.remove(name)
            except ValueError as e:
                log(f"Error: failed to remove {name} from the members list: {e}")
        non_voters_text = get_users_aliases_string(server_dataset, non_voters)

        game_link = "https://store.steampowered.com/app/" + str(game_data.steam_id)
        game_text = f"{game_data.id} - [{game_data.name}]({game_link}) {non_voters_text}"
        games_list.append(game_text)

    title_text = "Games list (shows non-voters)"
    games_list_text = "\n".join(games_list)
    # Determine if we can show all games in the embed
    chars_over_limit = len(title_text) + len(games_list_text) - EMBED_MAX_CHARACTERS
    if chars_over_limit > 0:
        games_list_text = games_list_text[:-chars_over_limit - 3] + "..."

    list_embed = discord.Embed(
        title=title_text,
        description=games_list_text,
        color=LIST_EMBED_COLOR
    )
    return list_embed


def generate_hog_embed(server_id):
    server_id = str(server_id)

    dataset = read_dataset()
    # Try to narrow down the dataset to this server
    if server_id not in dataset:
        log(f"Could not find server {server_id} in the dataset.")
        return None

    server_dataset = dataset[server_id]
    sorted_games = sort_games_by_score(server_dataset, finished_games=True)
    if len(sorted_games) == 0:
        log("No completed games found.")
        return None

    guild = bot.get_guild(int(server_id))
    if guild is None:
        log(f"Error: could not find server with ID {server_id}.")
        return None

    games_list = []
    for game_data, score in sorted_games:
        game_link = "https://store.steampowered.com/app/" + str(game_data.steam_id)
        game_text = f"{game_data.id} - [{game_data.name}]({game_link})"
        games_list.append(game_text)

    title_text = "Hall of Game"
    games_list_text = "\n".join(games_list)
    # Determine if we can show all games in the embed
    chars_over_limit = len(title_text) + len(games_list_text) - EMBED_MAX_CHARACTERS
    if chars_over_limit > 0:
        games_list_text = games_list_text[:-chars_over_limit - 3] + "..."

    list_embed = discord.Embed(
        title=title_text,
        description=games_list_text,
        color=LIST_EMBED_COLOR
    )
    return list_embed


async def get_live_message_object(server_id, message_type):
    """
    Gets the message object for one of the live updating messages.
    Currently supports "overview" and "list" as message types.
    """
    server_id = str(server_id)

    # Get the server dataset
    dataset = read_dataset()
    server_dataset = dataset.get(server_id)
    if server_dataset is None:
        log(f"Could not find server with ID {server_id} in dataset.")
        return None

    # Get the Discord server object
    server_object = bot.get_guild(int(server_id))
    if server_object is None:
        log(f"Discord could not find server with ID {server_id}.")
        return None

    # Get the channel ID in which the message was sent
    channel_id = server_dataset.get(f"{message_type}_channel_id")
    if channel_id in (None, 0):
        # This server does not have the specified message
        return None

    # Get the Discord channel object
    channel_object = server_object.get_channel(channel_id)
    if channel_object is None:
        log(f"Discord could not find channel with ID {channel_id}.")
        return None

    # Get the Discord message object
    message_id = server_dataset.get(f"{message_type}_message_id")
    if message_id in (None, 0):
        log(f"Error: {message_type}_message_id not found, but {message_type}_channel_id is present for server {server_id}.")
        return None

    message = await channel_object.fetch_message(message_id)
    return message


async def update_overview(server_id):
    server_id = str(server_id)

    overview_message = await get_live_message_object(server_id, "overview")
    if overview_message is None:
        return

    updated_overview_embed = generate_overview_embed(server_id)
    if updated_overview_embed is not None:
        await overview_message.edit(embed=updated_overview_embed)


async def update_list(server_id):
    server_id = str(server_id)

    list_message = await get_live_message_object(server_id, "list")
    if list_message is None:
        return

    updated_list_embed = generate_list_embed(server_id)
    if updated_list_embed is not None:
        await list_message.edit(embed=updated_list_embed)


async def update_hall_of_game(server_id):
    server_id = str(server_id)

    hog_message = await get_live_message_object(server_id, "hall_of_game")
    if hog_message is None:
        return

    updated_hog_embed = generate_hog_embed(server_id)
    if updated_hog_embed is not None:
        await hog_message.edit(embed=updated_hog_embed)


async def update_live_messages(server_id):
    await update_overview(server_id)
    await update_list(server_id)
    await update_hall_of_game(server_id)


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
    log(f"\n\n\n{datetime.datetime.now()}")
    log(f"{bot.user} has connected to Discord!")
    await update_dataset_steam_prices()
    log("Finished updating Steam prices")


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

    ctx = await bot.get_context(message)
    server_id = str(ctx.guild.id)
    # Check if we need to delete the bot's message
    if reaction.emoji == "❌":
        await message.delete()

        if len(message.embeds) == 0:
            return
        # Assume the message only has 1 embed, as multiple aren't possible
        embed = message.embeds[0]
        if embed.color == OVERVIEW_EMBED_COLOR:
            # The overview was just deleted, so clear it from the dataset as well
            dataset = read_dataset()
            dataset[server_id]["overview_message_id"] = 0
            dataset[server_id]["overview_channel_id"] = 0
            save_dataset(dataset)
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
            await update_live_messages(server_id)


@bot.command(name="update_prices", help="Retrieves the latest prices from Steam. Example: !update_prices.")
async def update_prices(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    await update_dataset_steam_prices()

    await update_live_messages(server_id)
    await ctx.message.delete()


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

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="remove", help="Removes a game from the list. Example: !remove \"game name\".")
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

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="finish", help="Marks a game as finished, moving it to the completed games list. Example: !finish \"game name\".")
async def finish_game(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game.")
        return

    # Create a FinishedGameData object for this game and save it
    finished_game = FinishedGameData(json_data=game_data.to_json())
    finished_games = dataset[server_id].get("finished_games", {})
    finished_games[str(game_data.id)] = finished_game.to_json()
    dataset[server_id]["finished_games"] = finished_games

    # Remove the game from the regular list and save the dataset again
    del dataset[server_id]["games"][str(game_data.id)]
    save_dataset(dataset)

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="enjoyed", help="Rate how much you enjoyed a game, between 0-10. Example: !enjoyed \"game name\" 7.5. Default rating is 5.")
async def enjoyed(ctx, game_name, score=5.0):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    try:
        score = float(score)
        assert 0 <= score <= 10
    except (ValueError, AssertionError):
        await ctx.send("Rating must be a number between 0 and 10.")
        return

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name, finished=True)
    if game_data is None:
        log(f"Could not find finished game: {str(game_data)}")
        await ctx.send("Could not find finished game. Please use: !finish \"game name\", to mark a game as finished.")
        return

    # Update the vote and save the new game data
    game_data.enjoyment_scores[str(ctx.author)] = score
    dataset[server_id]["finished_games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_hall_of_game(server_id)
    await ctx.message.delete()


@bot.command(name="hog", help=":boar:")
async def hall_of_game(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    hog_embed = generate_hog_embed(ctx.guild.id)
    if hog_embed is None:
        await ctx.send("Nothing to show (yet).")
        return

    message = await ctx.send(embed=hog_embed)

    dataset = read_dataset()

    # Store the new message ID
    dataset[server_id]["hall_of_game_message_id"] = message.id
    dataset[server_id]["hall_of_game_channel_id"] = ctx.channel.id
    save_dataset(dataset)

    await ctx.message.delete()


@bot.command(name="vote", help="Sets your preference for playing a game, between 0-10. Example: !vote \"game name\" 7.5. Default vote is 5.")
async def rate_game(ctx, game_name, score=5.0):
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

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="overview", help="Displays a live overview of the most promising games. Example: !display.")
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


@bot.command(name="list", help="Displays a sorted list of all games (does not update). Example: !list.")
async def list_games(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    list_embed = generate_list_embed(server_id)
    if list_embed is None:
        await ctx.send("No games registered for this server yet.")
        return

    message = await ctx.send(embed=list_embed)

    dataset = read_dataset()
    # Store the new message ID
    dataset[server_id]["list_message_id"] = message.id
    dataset[server_id]["list_channel_id"] = ctx.channel.id
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
async def add_tag(ctx, game_name, tag_text):
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

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="remove_tag", help="Removes a tag from a game. Example: !remove_tag \"game name\" \"PvP only\".")
async def remove_tag(ctx, game_name, tag_text):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    if tag_text not in game_data.tags:
        await ctx.send(f"Game \"{game_data.name}\" does not have tag \"{tag_text}\".")
        return

    # Remove the tag and save the new game data
    game_data.tags.remove(tag_text)
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="own", help="Sets whether you own a game or not. Example: !own \"game name\" no. Defaults to \"yes\".")
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

    await update_live_messages(server_id)
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

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="local", help="Sets whether a game can be played together with one copy. Example: !local \"game name\" no. Defaults to \"yes\".")
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

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="played", help="Sets whether you have played a game before or not. Example: !played \"game name\" no. Defaults to \"yes\".")
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

    await update_live_messages(server_id)
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

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="alias", help="Sets an alias for yourself, to be displayed in the overview. Example: !alias :sunglasses:. Leave empty to clear it.")
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

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="rename", help="Change the name of a game. Example: !rename \"game name\" \"new game name\".")
async def rename_game(ctx, game_name, new_game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)

    dataset = read_dataset()
    game_data = filter_game_dataset(dataset, server_id, game_name)
    if game_data is None:
        log(f"Could not find game: {str(game_data)}")
        await ctx.send("Could not find game. Please use: !add \"game name\", to add a new game.")
        return

    # Update the name and save the new game data
    game_data.name = new_game_name
    dataset[server_id]["games"][str(game_data.id)] = game_data.to_json()
    save_dataset(dataset)

    await update_live_messages(server_id)
    await ctx.message.delete()


@bot.command(name="affinity", help="Shows how similarly you vote to other people. Example: !affinity.")
async def rename_game(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = str(ctx.guild.id)
    username = str(ctx.author)

    dataset = read_dataset()

    # Narrow down the dataset to a specific server
    if server_id not in dataset:
        await ctx.send("No games registered for this server yet.")
        return
    game_dataset = dataset[server_id]["games"]

    similarity_scores = {}
    for game_json in game_dataset.values():
        votes = game_json.get("votes", {})
        # Skip this game if the user hasn't voted on it
        if username not in votes:
            continue

        base_vote = votes[username]
        # Check the votes for this game
        for user, vote in votes.items():
            if user == username:
                continue

            # If this is the first time we see this user, add them to the scores dict
            if user not in similarity_scores:
                similarity_scores[user] = {"error_sum": 0, "count": 0}

            similarity_scores[user]["error_sum"] += abs(base_vote - vote)
            similarity_scores[user]["count"] += 1

    similarity_percentages = []
    for user, stats in similarity_scores.items():
        if stats["count"] > 0:
            # Calculate the Mean Absolute Error
            mae = stats["error_sum"] / stats["count"]
            # Convert it to a percentage
            similarity = (1 - (mae / 10)) * 100
            similarity_percentages.append((user, round(similarity, 2)))

    # Sort it so the highest affinity shows up first
    similarity_percentages = sorted(similarity_percentages, key=lambda x: x[1], reverse=True)

    if len(similarity_percentages) == 0:
        affinity_text = "No people have voted on the same games."
    else:
        entries = []
        for user, affinity in similarity_percentages:
            entries.append(f"{user}: {affinity}%")
        affinity_text = "\n".join(entries)

    # Get info on the game and display it in an embed
    title = f"{username}'s affinity with others"
    affinity_embed = discord.Embed(
        title=title,
        description=affinity_text,
        color=AFFINITY_EMBED_COLOR
    )

    await ctx.send(embed=affinity_embed)
    await ctx.message.delete()


@bot.command(name="kick", help="Kicks a member from the server. Example: !kick \"member name\".")
async def kick(ctx, member_name):
    log(f"{ctx.author}: {ctx.message.content}")
    member_name = member_name.lower()
    if member_name in ["co-op game tracker", "coop game tracker", "coopgametracker", "co-op game tracker#0487", "coop game tracker#0487", "coopgametracker#0487"]:
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


@bot.command(name="view")
async def view(ctx):
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


@bot.command(name="hentie", help="Sends random hentie image.")
async def hentie(ctx):
    log(f"{ctx.author}: {ctx.message.content}")

    hentie_image_links = [
        "https://i.redd.it/u30f7kflnxb11.jpg",
        "https://pbs.twimg.com/media/FUeFpJDUAAA7Iyo?format=jpg&name=4096x4096",
        "https://ih1.redbubble.net/image.1568819551.7909/bg,f8f8f8-flat,750x,075,f-pad,750x1000,f8f8f8.jpg",
        "https://static.wikia.nocookie.net/walkingdead/images/0/00/Hen_in_a_tie.jpg",
        "http://farm4.staticflickr.com/3262/2610575538_b3e16d48c8_z.jpg",
    ]
    message = random.choice(hentie_image_links)
    await ctx.send(message)


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
