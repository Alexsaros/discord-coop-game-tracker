import os
import threading
import traceback
from collections import defaultdict
from typing import Optional

import discord
import asyncio
import time
import datetime
import subprocess
import flask
import shutil
from discord.ext import commands
from discord.ext.commands import CommandInvokeError
from discord.ui import View, Button, Select
from dotenv import load_dotenv
from apscheduler.triggers.cron import CronTrigger
import random
import hmac
import hashlib

from sqlalchemy.orm import joinedload, Session

from apis.steam import get_steam_game_price, get_steam_game_banner, search_steam_for_game, update_database_steam_prices
from database.utils import get_server_members
from services.bedtime import load_bedtime_scheduler_jobs
from shared import logger
from apis.discord import get_discord_guild_object, delete_message
from constants import EMBED_MAX_CHARACTERS, EMBED_DESCRIPTION_MAX_CHARACTERS, EMBED_MAX_FIELDS
from libraries import codenames
from shared.exceptions import BotException, GameNotFoundException
from shared.logger import log
from services import dice_roller, bedtime
from services.eight_ball import use_eight_ball
from services.free_games import check_free_to_keep_games, set_user_free_game_notifications
from database.db import db_session_scope, update_db
from database.models.game import Game, ReleaseState
from database.models.live_message import LiveMessageType, LiveMessage
from database.models.server import Server
from database.models.server_member import ServerMember
from database.models.user import User
from database.models.game_user_data import GameUserData
from services.horoscope import create_horoscope_embed
from services.tarot.tarot import create_random_tarot_embed
from shared.scheduler import get_scheduler
from shared.utils import parse_boolean

load_dotenv()
APP_ID = os.getenv("APP_ID")
PUBLIC_KEY = os.getenv("PUBLIC_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
STEAM_API_KEY = os.getenv("STEAM_API_KEY")
GITHUB_WEBHOOK_SECRET_TOKEN = os.getenv("GITHUB_WEBHOOK_SECRET_TOKEN")

DATABASE_FILE = "database/bot_data.db"
BACKUP_DIRECTORY = "backups"
MAX_BACKUPS = 20

EDIT_GAME_EMBED_COLOR = discord.Color.dark_blue()
LIST_EMBED_COLOR = discord.Color.blurple()
AFFINITY_EMBED_COLOR = discord.Color.purple()
LIST_PLAY_WITHOUT_EMBED_COLOR = discord.Color.red()
LIST_OWNED_GAMES_EMBED_COLOR = discord.Color.orange()

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

bot_updater = flask.Flask(__name__)


@bot_updater.route("/update-discord-bot-cooper", methods=["POST"])
def update_bot():
    # Check if the request has the correct signature/secret
    signature = flask.request.headers.get("X-Hub-Signature-256")
    if not signature:
        log("Incoming request does not have a `X-Hub-Signature-256` header.")
        flask.abort(403)
    sha_name, signature = signature.split("=")
    if sha_name != "sha256":
        log(f"Incoming request's X-Hub-Signature-256 does not use sha256, but `{sha_name}`.")
        flask.abort(403)
    # Using the secret, check if we compute the same HMAC for this request as the received HMAC
    computed_hmac = hmac.new(GITHUB_WEBHOOK_SECRET_TOKEN.encode(), msg=flask.request.data, digestmod=hashlib.sha256)
    if not hmac.compare_digest(computed_hmac.hexdigest(), signature):
        log("Incoming request does not have a matching HMAC/secret.")
        flask.abort(403)

    data = flask.request.json
    if data and data.get("ref") == "refs/heads/main":
        os.chdir("/home/alexsaro/discord-coop-game-tracker")
        output = subprocess.run(["git", "pull"], capture_output=True, text=True)

        log(output)
        log("Pulled new git commits. Shutting down the bot so it can restart...")
        threading.Thread(target=shutdown).start()
    return "", 200


def shutdown():
    time.sleep(1)       # Wait a second to give a chance for any clean-up
    bot.loop.stop()
    os._exit(0)


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
            await asyncio.sleep(2.5)
            await message.delete()

        # Send the actual help message
        await super().send_bot_help(mapping)


bot = commands.Bot(command_prefix="!", intents=intents, help_command=CustomHelpCommand())


async def send_error_message(exception):
    await logger.send_error_message(bot, exception)


def create_backup(file_to_backup=DATABASE_FILE):
    # Ensure the backup directory exists
    os.makedirs(BACKUP_DIRECTORY, exist_ok=True)

    # Create a new backup with a timestamp
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.basename(file_to_backup)
    backup_filepath = os.path.join(BACKUP_DIRECTORY, f"{filename}_{timestamp}.bak")
    shutil.copy2(file_to_backup, backup_filepath)
    log(f"Created backup: {backup_filepath}")

    # Get all the backups for the requested file, and sort them from old to new
    relevant_backups = [os.path.join(BACKUP_DIRECTORY, f) for f in os.listdir(BACKUP_DIRECTORY) if f.startswith(filename) and f.endswith(".bak")]
    backups = sorted(relevant_backups, key=os.path.getctime)

    # Remove the oldest backups if we have too many
    while len(backups) > MAX_BACKUPS:
        oldest_backup = backups.pop(0)
        os.remove(oldest_backup)
        log(f"Deleted old backup: {oldest_backup}")


def get_game(db_session: Session, server_id: int, game_name: str, finished=False) -> Game:
    """
    Returns the game's data from the database as a Game object.
    Raises a GameNotFoundException if the game was not found.
    """
    try:
        # Check if the game was passed as ID
        game_id = str(int(game_name))
        game = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.id == game_id)
                .filter(Game.finished.is_(finished))
                .first()
        )   # type: Game

        if game is None:
            # TODO find an easier way to handle these exception messages
            if finished:
                raise GameNotFoundException(f"Could not find finished game with ID \"{game_id}\". Use: !finish \"game name\", to mark a game as finished.")
            else:
                raise GameNotFoundException(f"Could not find game with ID \"{game_id}\". Use: !add \"game name\", to add a new game.")

        return game

    except ValueError:
        # A name was given to find the game
        game = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.name.ilike(game_name))
                .filter(Game.finished.is_(finished))
                .first()
        )   # type: Game

        if game is None:
            if finished:
                raise GameNotFoundException(f"Could not find finished game with name \"{game_name}\". Use: !finish \"game name\", to mark a game as finished.")
            else:
                raise GameNotFoundException(f"Could not find game with name \"{game_name}\". Use: !add \"game name\", to add a new game.")

        return game


def sort_games_by_score(games: list[Game], member_count: int) -> list[tuple[Game, int]]:
    game_scores = []

    for game in games:
        # Count the score for this game
        with db_session_scope() as db_session:
            game_user_data_list = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == game.server_id)
                    .filter(GameUserData.game_id == game.id)
                    .all()
            )   # type: list[GameUserData]

            if not game.finished:
                votes = [data.vote for data in game_user_data_list]
            else:
                votes = [data.enjoyment_score for data in game_user_data_list]

        total_score = sum(votes)
        # Use a score of 5 for the non-voters
        non_voter_count = member_count - len(votes)
        total_score += non_voter_count * 5

        game_scores.append((game, total_score))

    return sorted(game_scores, key=lambda x: x[1], reverse=True)


def get_users_aliases_string(server_id: int, user_ids: list[int]) -> str:
    with db_session_scope() as db_session:
        # Get each user's alias, falling back to their global name if not set
        users_text = ""
        members = (
            db_session.query(ServerMember)
                .options(joinedload(ServerMember.user))     # Also preemptively retrieve User data
                .filter(ServerMember.server_id == server_id)
                .filter(ServerMember.user_id.in_(user_ids))
                .all()
        )   # type: list[ServerMember]

        user_names = []
        user_aliases = []
        for member in members:
            if member.alias is not None:
                user_aliases.append(member.alias)
            else:
                user_names.append(member.user.global_name)

        users_text += " ".join(user_aliases)
        users_text += ", ".join(user_names)
        return users_text


def generate_price_text(game: Game) -> str:
    price_text = ""
    if game is None:
        return price_text
    if game.release_state != ReleaseState.RELEASED:
        price_text = "coming soon"
    elif game.price_original >= 0:
        price_original = game.price_original
        price_current = game.price_current

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

    return price_text


def get_game_embed_field(game: Game):
    """
    Gets the details of the given game from the dataset to be displayed in an embed field.
    Returns a dictionary with keys "name", "value", and "inline", as expected by Discord's embed field.
    """
    description = ""

    price_text = generate_price_text(game)
    if price_text != "":
        # If we have the Steam game ID, add a hyperlink on the game's price
        if game.steam_id:
            link = f"https://store.steampowered.com/app/{game.steam_id}"
            price_text = f"[{price_text}]({link})"

        description += f"\n> Price: {price_text}"

    with db_session_scope() as db_session:
        game_user_data_list = (
            db_session.query(GameUserData)
                .filter(GameUserData.server_id == game.server_id)
                .filter(GameUserData.game_id == game.id)
                .all()
        )   # type: list[GameUserData]

    voted_user_ids = [data.user_id for data in game_user_data_list if data.vote is not None]
    if voted_user_ids:
        description += "\n> Voted: "
        voters_text = get_users_aliases_string(game.server_id, voted_user_ids)
        description += voters_text

    if game.player_count is not None:
        player_count_text = EMOJIS[f"{game.player_count}players"]
        description += f"\n> Players: {player_count_text}"

    # Do not display who owns a game if the game is free, as you can't buy a free game
    owned_user_data_list = [data for data in game_user_data_list if data.owned is not None]
    if (owned_user_data_list or game.local) and game.price_original != 0:
        description += "\n> Owned: "

        if owned_user_data_list:
            # Sums the True/False values, with them corresponding to 1/0
            owned_count = sum(data.owned for data in owned_user_data_list)
            description += EMOJIS["owned"] * owned_count
            description += EMOJIS["not_owned"] * (len(owned_user_data_list) - owned_count)

        if game.local:
            description += "(" + EMOJIS["local"] + ")"

    played_before_user_data_list = [data for data in game_user_data_list if data.played_before is not None]
    if played_before_user_data_list:
        description += "\n> Experience: "
        # Sums the True/False values, with them corresponding to 1/0
        played_before_count = sum(data.played_before for data in played_before_user_data_list)
        description += EMOJIS["experienced"] * played_before_count
        description += EMOJIS["new"] * (len(played_before_user_data_list) - played_before_count)

    tags = game.tags
    if len(tags) > 0:
        description += "\n> " + "\n> ".join(tags)

    description = description.strip()

    embed_field_info = {
        "name": f"{game.id} - {game.name}",
        "value": description,
        "inline": False,
    }
    return embed_field_info


def paginate_embed_fields(embed: discord.Embed):
    embeds = []
    new_embed = discord.Embed(title=embed.title, color=embed.color)
    embeds.append(new_embed)
    title_length = len(embed.title) + 15  # Add 15 extra characters as wiggle room, to support page numbers into the triple digits
    current_embed_length = title_length

    for field in embed.fields:
        field_length = len(field.name) + len(field.value)
        # Check if there's enough space left for this field in the embed, if not, create a new embed
        if ((current_embed_length + field_length) > EMBED_MAX_CHARACTERS) or \
                (len(new_embed.fields) >= EMBED_MAX_FIELDS):
            new_embed = discord.Embed(title=embed.title, color=embed.color)
            embeds.append(new_embed)
            current_embed_length = title_length

        # Add the field to the new embed
        current_embed_length += field_length
        new_embed.add_field(name=field.name, value=field.value, inline=field.inline)

    # Update each embed's title to indicate their page number
    if len(embeds) > 1:
        for i, new_embed in enumerate(embeds, 1):
            new_embed.title += f" (page {i}/{len(embeds)})"

    return embeds


def paginate_embed_description(embed: discord.Embed) -> list[discord.Embed]:
    embeds = []
    current_embed_description = ""

    for line in embed.description.split("\n"):
        # Check if there's enough space left for this line in the embed, if not, create a new embed with the description that fits
        if (len(current_embed_description) + len(line)) > EMBED_DESCRIPTION_MAX_CHARACTERS:
            embeds.append(discord.Embed(title=embed.title, description=current_embed_description, color=embed.color))
            current_embed_description = ""

        current_embed_description += "\n" + line

    embeds.append(discord.Embed(title=embed.title, description=current_embed_description, color=embed.color))

    # Update each embed's title to indicate their page number
    if len(embeds) > 1:
        for i, new_embed in enumerate(embeds, 1):
            new_embed.title += f" (page {i}/{len(embeds)})"

    return embeds


async def generate_list_embeds(server_id: int) -> Optional[list[discord.Embed]]:
    guild = await get_discord_guild_object(bot, server_id)
    if guild is None:
        return None

    with db_session_scope() as db_session:
        games = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.finished.is_(False))
                .all()
        )   # type: list[Game]

        members = get_server_members(server_id)
        sorted_games = sort_games_by_score(games, len(members))

        games_list = []     # type: list[str]
        for game, score in sorted_games:
            # Get everyone who hasn't voted yet
            non_voters_ids = [member.user_id for member in members]

            voters_ids = (
                db_session.query(GameUserData.user_id)
                    .filter(GameUserData.server_id == server_id)
                    .filter(GameUserData.game_id == game.id)
                    .filter(GameUserData.vote.isnot(None))
                    .all()
            )  # type: list[tuple[int]]
            voters_ids = [voter_id[0] for voter_id in voters_ids]   # type: list[int]

            for voter_id in voters_ids:
                if voter_id in non_voters_ids:
                    non_voters_ids.remove(voter_id)
            non_voters_text = get_users_aliases_string(server_id, non_voters_ids)

            game_text = f"{game.id} -"
            if game.steam_id is not None:
                game_link = "https://store.steampowered.com/app/" + str(game.steam_id)
                game_text += f" [{game.name}]({game_link})"
            else:
                game_text += " " + game.name
            price_text = generate_price_text(game)
            if price_text:
                game_text += " " + price_text
            if non_voters_text:
                game_text += " " + non_voters_text

            games_list.append(game_text)

        title_text = "Games list (shows non-voters)"
        games_list_text = "\n".join(games_list)

        list_embed = discord.Embed(
            title=title_text,
            description=games_list_text,
            color=LIST_EMBED_COLOR
        )
        embeds = paginate_embed_description(list_embed)
        return embeds


async def generate_hog_embed(server_id: int):
    guild = await get_discord_guild_object(bot, server_id)
    if guild is None:
        return None

    with db_session_scope() as db_session:
        # Get all finished games
        games = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.finished.is_(True))
                .all()
        )   # type: list[Game]

        if len(games) == 0:
            log("No finished games found.")
            return None

        members = get_server_members(server_id)
        sorted_games = sort_games_by_score(games, len(members))

        games_list = []
        for game, score in sorted_games:
            if game.steam_id is None:
                game_text = f"{game.id} - {game.name}"
            else:
                game_link = "https://store.steampowered.com/app/" + str(game.steam_id)
                game_text = f"{game.id} - [{game.name}]({game_link})"
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


async def get_live_message_object(server_id: int, message_type: LiveMessageType) -> Optional[discord.Message]:
    """
    Gets the message object for one of the live updating messages.
    Returns None if not found.
    """
    # Get the Discord guild object
    guild_object = await get_discord_guild_object(bot, server_id)
    if guild_object is None:
        return None

    with db_session_scope() as db_session:
        live_message = (
            db_session.query(LiveMessage)
                .filter(LiveMessage.server_id == server_id)
                .filter(LiveMessage.message_type == message_type)
                .first()
        )   # type: LiveMessage
        if live_message is None:
            # This server does not have the specified message
            return None

        # Get the Discord channel object
        channel_object = await guild_object.fetch_channel(live_message.channel_id)
        if channel_object is None:
            log(f"Discord could not find channel with ID {live_message.channel_id}. It has likely been deleted. Removing child message from the dataset...")
            db_session.delete(live_message)
            return None

        # Get the Discord message object
        try:
            return await channel_object.fetch_message(live_message.message_id)
        except discord.errors.NotFound:
            log(f"Could not find {message_type} with ID {live_message.message_id}. It has likely been deleted. Removing it from the dataset...")
            db_session.delete(live_message)
            return None


class PageButtonsView(View):

    def __init__(self, embed_title: str, message_id: int, update_function: callable, function_argument):
        super().__init__(timeout=None)
        self.update_function = update_function
        self.function_argument = function_argument

        self.current_page = get_current_page_from_message_title(embed_title)
        total_pages = get_total_pages_from_message_title(embed_title)
        disabled_previous = self.current_page <= 1
        disabled_next = self.current_page >= total_pages

        self.add_item(Button(style=discord.ButtonStyle.blurple, label="Previous page", custom_id=f"{message_id}_previousPage", disabled=disabled_previous))
        self.add_item(Button(style=discord.ButtonStyle.grey, label=f"Page {self.current_page}/{total_pages}", custom_id=f"{message_id}_pageNumber", disabled=True))
        self.add_item(Button(style=discord.ButtonStyle.blurple, label="Next page", custom_id=f"{message_id}_nextPage", disabled=disabled_next))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            # noinspection PyUnresolvedReferences
            await interaction.response.defer()

            action = interaction.data.get("custom_id").split("_")[-1]
            new_page = self.current_page
            if action == "previousPage":
                new_page -= 1
            elif action == "nextPage":
                new_page += 1

            await self.update_function(self.function_argument, new_page)
        except Exception as e:
            await send_error_message(e)

        return True


def get_current_page_from_message_title(embed_title: str) -> int:
    if "(page " not in embed_title:
        return 1
    page_info = embed_title.split("page ")[-1].rstrip(")")
    current_page = int(page_info.split("/")[0])
    return max(current_page, 1)


def get_total_pages_from_message_title(embed_title: str) -> int:
    if "(page " not in embed_title:
        return 1
    page_info = embed_title.split("page ")[-1].rstrip(")")
    total_pages = int(page_info.split("/")[-1])
    return total_pages


async def update_list(server_id: int, page_number: int = None) -> None:
    list_message = await get_live_message_object(server_id, LiveMessageType.LIST)
    if list_message is None:
        return

    list_embeds = (await generate_list_embeds(server_id))
    if page_number is None:
        current_page = get_current_page_from_message_title(list_message.embeds[0].title)
        page_number = min(current_page, len(list_embeds))
    updated_list_embed = list_embeds[page_number - 1]

    page_buttons_view = PageButtonsView(updated_list_embed.title, list_message.id, update_list, server_id)
    try:
        if updated_list_embed is not None:
            await list_message.edit(embed=updated_list_embed, view=page_buttons_view)
    except Exception as e:
        await send_error_message(e)


async def update_hall_of_game(server_id: int) -> None:
    hog_message = await get_live_message_object(server_id, LiveMessageType.HALL_OF_GAME)
    if hog_message is None:
        return

    updated_hog_embed = await generate_hog_embed(server_id)
    try:
        if updated_hog_embed is not None:
            await hog_message.edit(embed=updated_hog_embed)
    except Exception as e:
        await send_error_message(e)


async def update_live_messages(server_id: int, skip_hog=False) -> None:
    await update_list(server_id)
    if not skip_hog:
        await update_hall_of_game(server_id)


async def update_all_lists() -> None:
    with db_session_scope() as db_session:
        servers = db_session.query(Server).all()    # type: list[Server]

        for server in servers:
            await update_list(server.id)


async def update_steam_prices() -> None:
    await update_database_steam_prices()
    await update_all_lists()


async def load_list_views():
    with db_session_scope() as db_session:
        list_messages = (
            db_session.query(LiveMessage)
                .filter(LiveMessage.message_type == LiveMessageType.LIST)
                .all()
        )   # type: list[LiveMessage]

    for list_message in list_messages:
        list_message_obj = await get_live_message_object(list_message.server_id, LiveMessageType.LIST)
        if list_message_obj is not None:
            bot.add_view(PageButtonsView(list_message_obj.embeds[0].title, list_message_obj.id, update_list, list_message.server_id))


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
    await load_list_views()

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


@bot.command(name="update_prices", help="Retrieves the latest prices from Steam. Example: !update_prices.")
async def update_prices(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    await update_steam_prices()

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="add", help="Adds a new game to the list. Example: !add \"game name\".")
async def add_game(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    try:
        int(game_name)
        await ctx.send("Game name cannot be a number.")
        return
    except ValueError:
        pass

    with db_session_scope() as db_session:
        try:
            game = get_game(db_session, server_id, game_name, finished=True)
            log(f"Game already finished: {str(game.name)}")
            await ctx.send("This game has already been finished.")
            return
        except GameNotFoundException:
            pass

        try:
            game = get_game(db_session, server_id, game_name)
            log(f"Game already added: {str(game.name)}")
            await ctx.send("This game has already been added.")
            return
        except GameNotFoundException:
            last_game_id = (
                db_session.query(Game.id)
                    .filter(Game.server_id == server_id)
                    .order_by(Game.id.desc())
                    .limit(1)
                    .scalar()
            )
            game_id = (last_game_id + 1) if last_game_id is not None else 1
            game = Game(
                server_id=server_id,
                id=game_id,
                name=game_name,
                submitter=str(ctx.author)
            )

        # Search Steam for this game and save the info
        steam_game_info = search_steam_for_game(game_name)
        if steam_game_info is not None and \
                "id" in steam_game_info:
            game.steam_id = steam_game_info["id"]
            game_price = await get_steam_game_price(game.steam_id)
            if game_price is not None:
                game.price_current = game_price["price_current"]
                game.price_original = game_price["price_original"]

        db_session.add(game)

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="remove", help="Removes a game from the list. Example: !remove \"game name\".")
async def remove_game(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        # Remove the game from the database
        db_session.delete(game)

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="finish", help="Marks a game as finished, moving it to the completed games list. Example: !finish \"game name\".")
async def finish_game(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        game.finished = True
        game.finished_timestamp = time.time()

        hog_message = await get_live_message_object(server_id, LiveMessageType.HALL_OF_GAME)
        if hog_message:
            hog_channel = hog_message.channel
        else:
            hog_channel = ctx.channel

        game_text = game.name
        if game.steam_id is not None:
            game_link = f"https://store.steampowered.com/app/{game.steam_id}"
            game_text = f"[{game_text}](<{game_link}>)"     # Surround the link in <> to prevent a link embed from being added

        # Create a thread for the game and its screenshots in the hall of game channel
        banner_file = get_steam_game_banner(game.steam_id)
        if banner_file is None:
            banner_message = await hog_channel.send(game_text)
        else:
            banner_message = await hog_channel.send(game_text, file=banner_file)
        await banner_message.create_thread(name=game.name)
        await hog_channel.create_thread(name=f"{game.name} screenshots", type=discord.ChannelType.public_thread)

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="enjoyed", help="Rate how much you enjoyed a game, between 0-10. Example: !enjoyed \"game name\" 7.5. Default rating is 5.")
async def enjoyed(ctx, game_name, score=5.0):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    try:
        score = float(score)
        assert 0 <= score <= 10
    except (ValueError, AssertionError):
        await ctx.send("Rating must be a number between 0 and 10.")
        return

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name, finished=True)
        game_user_data = db_session.get(GameUserData, (server_id, game.id, user_id))    # type: GameUserData
        if game_user_data is None:
            game_user_data = GameUserData(server_id=server_id, game_id=game.id, user_id=user_id)
            db_session.add(game_user_data)

        game_user_data.enjoyment_score = score

    await update_hall_of_game(server_id)
    await delete_message(ctx.message)


@bot.command(name="hog", help=":boar:")
async def hall_of_game(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    hog_embed = await generate_hog_embed(ctx.guild.id)
    if hog_embed is None:
        await ctx.send("Nothing to show (yet).")
        return

    message = await ctx.send(embed=hog_embed)   # type: discord.Message

    with db_session_scope() as db_session:
        hog_live_message = LiveMessage(
            server_id=server_id,
            channel_id=message.channel.id,
            message_id=message.id,
            message_type=LiveMessageType.HALL_OF_GAME,
        )
        db_session.add(hog_live_message)

    await delete_message(ctx.message)


@bot.command(name="vote", help="Sets your preference for playing a game, between 0-10. Example: !vote \"game name\" 7.5. Default vote is 5.")
async def vote_game(ctx, game_name, score=5.0):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    try:
        score = float(score)
        assert 0 <= score <= 10
    except (ValueError, AssertionError):
        await ctx.send("Score must be a number between 0 and 10.")
        return

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)
        game_user_data = db_session.get(GameUserData, (server_id, game.id, user_id))  # type: GameUserData
        if game_user_data is None:
            game_user_data = GameUserData(server_id=server_id, game_id=game.id, user_id=user_id)
            db_session.add(game_user_data)

        game_user_data.vote = score

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="list", help="Displays a sorted list of all games. Example: !list.")
async def list_games(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    list_embed = (await generate_list_embeds(server_id))[0]
    if list_embed is None:
        await ctx.send("No games registered for this server yet.")
        return

    # Remove the buttons from the old list message
    list_message_old = await get_live_message_object(server_id, LiveMessageType.LIST)
    if list_message_old is not None:
        await list_message_old.edit(embed=list_embed, view=None)

        with db_session_scope() as db_session:
            # Delete the old list message from the database
            list_live_message_old = db_session.get(LiveMessage, list_message_old.id)    # type: LiveMessage
            if list_live_message_old is not None:
                db_session.delete(list_live_message_old)

    list_message = await ctx.send(embed=list_embed)
    page_buttons_view = PageButtonsView(list_embed.title, list_message.id, update_list, server_id)
    await list_message.edit(embed=list_embed, view=page_buttons_view)

    with db_session_scope() as db_session:
        list_live_message = LiveMessage(
            server_id=server_id,
            channel_id=list_message.channel.id,
            message_id=list_message.id,
            message_type=LiveMessageType.LIST,
        )
        db_session.add(list_live_message)

    await delete_message(ctx.message)


@bot.command(name="play_without", help="Displays a sorted list of games that the given user rated low. Example: !play_without alexsaro. :cry:")
async def play_without(ctx, username):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        user = (
            db_session.query(User)
                .filter(User.global_name.ilike(username))
                .first()
        )   # type: User
        if user is None:
            await ctx.send(f"Could not find user named \"{username}\".")
            return

        members = get_server_members(server_id)
        member_count = len(members)
        game_scores = []    # type: list[tuple[Game, int]]

        games = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.finished.is_(False))
                .all()
        )   # type: list[Game]

        for game in games:
            game_user_data_votes = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == server_id)
                    .filter(GameUserData.game_id == game.id)
                    .filter(GameUserData.vote.isnot(None))
                    .all()
            )  # type: list[GameUserData]

            # Skip games that the user voted 5 or higher on
            vote_user = next((data.vote for data in game_user_data_votes if data.user_id == user.id), 5)
            if vote_user >= 5:
                continue

            # Count the score for this game
            total_score = 0
            for data in game_user_data_votes:
                if data.user_id != user.id:
                    total_score += data.vote
                else:
                    total_score -= data.vote * member_count
            # Use a score of 5 for the non-voters
            non_voters_ids = member_count - len(game_user_data_votes)
            total_score += non_voters_ids * 5

            game_scores.append((game, total_score))

        sorted_games = sorted(game_scores, key=lambda x: x[1], reverse=True)

        games_list = []     # type: list[str]
        for game, score in sorted_games:
            game_user_data_votes = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == server_id)
                    .filter(GameUserData.game_id == game.id)
                    .filter(GameUserData.vote.isnot(None))
                    .all()
            )  # type: list[GameUserData]

            # Get everyone who hasn't voted yet
            non_voters_ids = [member.id for member in members]
            for data in game_user_data_votes:
                if data.user_id in non_voters_ids:
                    non_voters_ids.remove(data.user_id)
            non_voters_text = get_users_aliases_string(server_id, non_voters_ids)

            game_text = f"{game.id} -"
            if game.steam_id is not None:
                game_link = "https://store.steampowered.com/app/" + str(game.steam_id)
                game_text += f" [{game.name}]({game_link})"
            else:
                game_text += " " + game.name
            price_text = generate_price_text(game)
            if price_text:
                game_text += " " + generate_price_text(game)
            if non_voters_text:
                game_text += " " + non_voters_text

            games_list.append(game_text)

        title_text = f"Potential games to play without {user.global_name}"
        games_list_text = "\n".join(games_list)

        list_embed = discord.Embed(
            title=title_text,
            description=games_list_text,
            color=LIST_PLAY_WITHOUT_EMBED_COLOR
        )
        embeds = paginate_embed_description(list_embed)
        list_embed = embeds[0]

        await ctx.send(embed=list_embed)

    await delete_message(ctx.message)


@bot.command(name="owned_games", help="Displays a list of games that everyone has marked as owned. Example: !owned_games.")
async def display_owned_games(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        members = get_server_members(server_id)
        member_count = len(members)

        games = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.finished.is_(False))
                .all()
        )   # type: list[Game]

        owned_games = []    # type: list[Game]
        for game in games:
            game_user_data_list = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == game.server_id)
                    .filter(GameUserData.game_id == game.id)
                    .all()
            )   # type: list[GameUserData]

            # Sums the True/False values, with them corresponding to 1/0
            owned_count = sum(data.owned for data in game_user_data_list)
            if owned_count >= member_count:
                owned_games.append(game)

        games_list = []
        for game in owned_games:
            game_text = f"{game.id} -"
            if game.steam_id is not None:
                game_link = f"https://store.steampowered.com/app/{game.steam_id}"
                game_text += f" [{game.name}]({game_link})"
            else:
                game_text += " " + game.name
            price_text = generate_price_text(game)
            if price_text:
                game_text += " " + generate_price_text(game)

            games_list.append(game_text)

        title_text = f"Games owned by everyone"
        games_list_text = "\n".join(games_list)

        list_embed = discord.Embed(
            title=title_text,
            description=games_list_text,
            color=LIST_OWNED_GAMES_EMBED_COLOR
        )
        embeds = paginate_embed_description(list_embed)
        list_embed = embeds[0]

        await ctx.send(embed=list_embed)

    await delete_message(ctx.message)


@bot.command(name="edit", help="Displays the given game as a message to be able edit it using its reactions. Example: !edit \"game name\".")
async def edit(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

    edit_game = EditGame(game.server_id, game.id, ctx.channel.id)
    await edit_game.send_message()

    await delete_message(ctx.message)


class EditGame:

    def __init__(self, server_id: int, game_id: int, channel_id: int):
        self.server_id = server_id
        self.game_id = game_id
        self.channel_id = channel_id
        self.message_object = None

    async def send_message(self):
        channel_object = await bot.fetch_channel(self.channel_id)

        game_embed = self.get_embed()
        game_view = self.EditGameView(self)
        self.message_object = await channel_object.send(embed=game_embed, view=game_view)    # type: discord.Message

    async def update_message(self):
        game_embed = self.get_embed()
        game_view = self.EditGameView(self)
        await self.message_object.edit(embed=game_embed, view=game_view)    # type: discord.Message

        await update_live_messages(self.server_id, skip_hog=True)

    def get_game(self, db_session: Session) -> Game:
        return (
            db_session.query(Game)
                .filter(Game.server_id == self.server_id)
                .filter(Game.id == self.game_id)
                .filter(Game.finished.is_(False))
                .first()
        )  # type: Game

    def get_embed(self):
        with db_session_scope() as db_session:
            game = self.get_game(db_session)

            # Get info on the game and display it in an embed
            embed_field_info = get_game_embed_field(game)
            title = embed_field_info["name"]
            embed_field_info["name"] = ""
            game_embed = discord.Embed(title=title, color=EDIT_GAME_EMBED_COLOR)
            game_embed.add_field(**embed_field_info)
            return game_embed

    async def delete_message(self):
        await self.message_object.delete()

    class EditGameView(View):

        def __init__(self, edit_game_object):
            super().__init__(timeout=None)
            self.edit_game_object = edit_game_object    # type: EditGame

            self.add_item(self.edit_game_object.VoteMenu(self.edit_game_object))
            self.add_item(Button(style=discord.ButtonStyle.blurple, label="Toggle owned", custom_id="owned"))
            self.add_item(Button(style=discord.ButtonStyle.blurple, label="Toggle played before", custom_id="played_before"))
            self.add_item(Button(style=discord.ButtonStyle.grey, label="Toggle single copy required", custom_id="local"))
            self.add_item(self.edit_game_object.PlayersMenu(self.edit_game_object))
            self.add_item(Button(style=discord.ButtonStyle.red, label="Close", custom_id="close"))

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            try:
                with db_session_scope() as db_session:
                    await interaction.response.defer()

                    user_id = interaction.user.id
                    button_id = interaction.data.get("custom_id")
                    game = self.edit_game_object.get_game(db_session)
                    game_user_data = db_session.get(GameUserData, (game.server_id, game.id, user_id))  # type: GameUserData
                    if game_user_data is None:
                        game_user_data = GameUserData(server_id=game.server_id, game_id=game.id, user_id=user_id)
                        db_session.add(game_user_data)

                    if button_id == "owned":
                        owned = game_user_data.owned if game_user_data.owned is not None else False
                        game_user_data.owned = not owned
                    elif button_id == "played_before":
                        played_before = game_user_data.played_before if game_user_data.played_before is not None else False
                        game_user_data.played_before = not played_before
                    elif button_id == "local":
                        game.local = not game.local
                    elif button_id == "close":
                        await self.edit_game_object.delete_message()
                        return True
                    else:
                        return True

                await self.edit_game_object.update_message()

            except Exception as e:
                await send_error_message(e)

            return True

    class VoteMenu(Select):
        def __init__(self, edit_game_object):
            self.edit_game_object = edit_game_object    # type: EditGame
            # The options range from 10 to 0
            options = [discord.SelectOption(label=str(i), value=str(i)) for i in range(10, -1, -1)]
            super().__init__(placeholder="Vote", options=options)

        async def callback(self, interaction: discord.Interaction):

            try:
                with db_session_scope() as db_session:
                    score = int(self.values[0])
                    user_id = interaction.user.id
                    game = self.edit_game_object.get_game(db_session)

                    game_user_data = db_session.get(GameUserData, (game.server_id, game.id, user_id))   # type: GameUserData
                    if game_user_data is None:
                        game_user_data = GameUserData(server_id=game.server_id, game_id=game.id, user_id=user_id)
                        db_session.add(game_user_data)

                    game_user_data.vote = score

                await self.edit_game_object.update_message()

            except Exception as e:
                await send_error_message(e)

    class PlayersMenu(Select):
        def __init__(self, edit_game_object):
            self.edit_game_object = edit_game_object    # type: EditGame
            # The options range from 1 to 4
            options = [discord.SelectOption(label=str(i), value=str(i)) for i in range(1, 5)]
            super().__init__(placeholder="Player count", options=options)

        async def callback(self, interaction: discord.Interaction):
            try:
                with db_session_scope() as db_session:
                    player_count = int(self.values[0])
                    game = self.edit_game_object.get_game(db_session)
                    game.player_count = player_count

                await self.edit_game_object.update_message()

            except Exception as e:
                await send_error_message(e)


@bot.command(name="tag", help="Adds an informative tag to a game. Example: !tag \"game name\" \"PvP only\".")
async def add_tag(ctx, game_name, tag_text):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        game.tags.append(tag_text)

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="remove_tag", help="Removes a tag from a game. Example: !remove_tag \"game name\" \"PvP only\".")
async def remove_tag(ctx, game_name, tag_text):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        if tag_text not in game.tags:
            await ctx.send(f"Game \"{game.name}\" does not have tag \"{tag_text}\".")
            return

        game.tags.remove(tag_text)

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="own", help="Sets whether you own a game or not. Example: !own \"game name\" no. Defaults to \"yes\".")
async def own(ctx, game_name, owns_game="yes"):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    owned = parse_boolean(owns_game)

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)
        game_user_data = db_session.get(GameUserData, (server_id, game.id, user_id))  # type: GameUserData
        if game_user_data is None:
            game_user_data = GameUserData(server_id=server_id, game_id=game.id, user_id=user_id)
            db_session.add(game_user_data)

        game_user_data.owned = owned
        if not owned:
            game_user_data.played_before = False

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="players", help="Sets with how many players a game can be played, ranging from 1-4. Example: !players \"game name\" 4.")
async def players(ctx, game_name, player_count):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    try:
        player_count = int(player_count)
        assert 1 <= player_count <= 4
    except (ValueError, AssertionError):
        await ctx.send("Player count must be a number between 1 and 4.")
        return

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        game.player_count = player_count

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="local", help="Sets whether a game can be played together with one copy. Example: !local \"game name\" no. Defaults to \"yes\".")
async def set_local(ctx, game_name, is_local="yes"):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    local = parse_boolean(is_local)

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        game.local = local

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="played", help="Sets whether you have played a game before or not. Example: !played \"game name\" no. Defaults to \"yes\".")
async def set_played(ctx, game_name, played_before="yes"):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    experienced = parse_boolean(played_before)

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)
        game_user_data = db_session.get(GameUserData, (server_id, game.id, user_id))    # type: GameUserData
        if game_user_data is None:
            game_user_data = GameUserData(server_id=server_id, game_id=game.id, user_id=user_id)
            db_session.add(game_user_data)

        game_user_data.played_before = experienced

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="steam_id", help="Links a game to a steam ID for the purpose of retrieving prices. Example: !steam_id \"game name\" 105600.")
async def set_steam_id(ctx, game_name, steam_id):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    try:
        steam_id = int(steam_id)
        assert steam_id >= 0
    except (ValueError, AssertionError):
        await ctx.send("Steam ID must be a positive number.")
        return

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        # Update the "steam_id" field, retrieve the price again, and save the new game data
        game.steam_id = steam_id
        steam_game_info = await get_steam_game_price(steam_id)
        # Default to no price if the Steam game couldn't be found
        game.price_current = None
        game.price_original = None
        if steam_game_info is not None:
            game.price_current = steam_game_info["price_current"]
            game.price_original = steam_game_info["price_original"]

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="alias", help="Sets an alias for yourself, to be displayed in the overview. Example: !alias :sunglasses:. Leave empty to clear it.")
async def set_alias(ctx, new_alias=None):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    with db_session_scope() as db_session:
        server_member = db_session.get(ServerMember, (user_id, server_id))  # type: ServerMember

        server_member.alias = new_alias

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="rename", help="Change the name of a game. Example: !rename \"game name\" \"new game name\".")
async def rename_game(ctx, game_name, new_game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        game.name = new_game_name

    await update_live_messages(server_id)
    await delete_message(ctx.message)


@bot.command(name="affinity", help="Shows how similarly you vote to other people. Example: !affinity.")
async def show_affinity(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    with db_session_scope() as db_session:
        game_user_data_votes = (
            db_session.query(GameUserData)
                .filter(GameUserData.server_id == server_id)
                .filter(GameUserData.vote.isnot(None))
                .all()
        )   # type: list[GameUserData]

        vote_data_by_game = defaultdict(list)   # type: dict[int, list[GameUserData]]
        for data in game_user_data_votes:
            vote_data_by_game[data.game_id].append(data)

        similarity_scores = defaultdict(lambda: defaultdict(int))   # type: dict[int, dict[str, int]]
        for game_id, game_vote_data in vote_data_by_game.items():
            # Skip this game if the user hasn't voted on it
            user_data = next((data for data in game_vote_data if data.user_id == user_id), None)
            if user_data is None:
                continue

            # Check the votes for this game
            for data in game_vote_data:
                if data.user_id == user_id:
                    continue

                similarity_scores[data.user_id]["error_sum"] += abs(user_data.vote - data)
                similarity_scores[data.user_id]["votes"] += 1

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

        user_db_entry = db_session.get(User, user_id)   # type: User

        # Get info on the game and display it in an embed
        title = f"{user_db_entry.global_name}'s affinity with others"
        affinity_embed = discord.Embed(
            title=title,
            description=affinity_text,
            color=AFFINITY_EMBED_COLOR
        )

    await ctx.send(embed=affinity_embed)
    await delete_message(ctx.message)


@bot.command(name="send_me_free_games", help="Opt in or out of receiving a message when a game is free to keep. Example: !send_me_free_games no. Defaults to \"yes\".")
async def send_me_free_games(ctx, notify_on_free_game="yes"):
    log(f"{ctx.author}: {ctx.message.content}")
    user_id = ctx.author.id

    notify = parse_boolean(notify_on_free_game)
    await set_user_free_game_notifications(bot, user_id, notify)

    await delete_message(ctx.message)


@bot.command(name="bedtime", help="Sets a reminder for your bedtime (CET). Example: !bedtime 21:30.")
async def set_bedtime(ctx, bedtime_time):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    await bedtime.set_bedtime(bot, server_id, user_id, bedtime_time)

    await delete_message(ctx.message)


@bot.command(name="tarot", help="Draws a major arcana tarot card. Example: !tarot.")
async def tarot(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    username = str(ctx.author)

    tarot_embed, tarot_file = create_random_tarot_embed(username)

    await ctx.send(embed=tarot_embed, file=tarot_file)
    await delete_message(ctx.message)


@bot.command(name="horoscope", help="Divines your daily horoscope. Example: !horoscope.")
async def horoscope(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    username = str(ctx.author)

    horoscope_embed = create_horoscope_embed(username)

    await ctx.send(embed=horoscope_embed)
    await delete_message(ctx.message)


@bot.command(name="kick", help="Kicks a member from the server. Example: !kick \"member name\".")
async def kick(ctx, member_name):
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


@bot.command(name="8ball", help="Use the magic eight ball to answer your yes-or-no question.")
async def eight_ball(ctx):
    log(f"{ctx.author}: {ctx.message.content}")

    answer = use_eight_ball()

    await ctx.send(answer)


@bot.command(name="choose", help="Randomly chooses one of the given options. Example: !choose red green \"light blue\".")
async def choose(ctx, *options):
    log(f"{ctx.author}: {ctx.message.content}")

    selected_option = random.choice(options)
    options_string = ", ".join(options)
    message_text = f"Possible options: {options_string}.\nChosen: **{selected_option}**."
    await ctx.send(message_text)
    await delete_message(ctx.message)


@bot.command(name="roll", help="Performs the given dice rolls and shows the result. Example: !roll 2d8+3.")
async def roll_dice(ctx, expression):
    log(f"{ctx.author}: {ctx.message.content}")
    username = str(ctx.author)

    message_text = dice_roller.roll_dice(username, expression)

    await ctx.send(message_text)
    await delete_message(ctx.message)


@bot.command(name="codenames", help="Start a Codenames game.")
async def start_codenames(ctx):
    log(f"{ctx.author}: {ctx.message.content}")

    await codenames.create_new_game(ctx)
    await delete_message(ctx.message)


@bot.command(name="codenames_settings", help="Open the settings menu for Codenames.")
async def codenames_settings(ctx):
    log(f"{ctx.author}: {ctx.message.content}")

    await codenames.show_settings(ctx)
    await delete_message(ctx.message)


@bot.event
async def on_command_error(ctx, error):
    # If this was an intended exception, just send the exception message to the channel
    if isinstance(error, CommandInvokeError):
        if isinstance(error.original, BotException):
            log(error.original.message)
            await ctx.send(error.original.message)
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
    # Start a thread that will restart this script whenever a Git commit has been pushed to the repo
    updater_thread = threading.Thread(target=bot_updater.run, kwargs={"host": "127.0.0.1", "port": 5500})
    updater_thread.start()

    update_db()

    # Allows for running multiple threads if needed in the future
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(bot.start(BOT_TOKEN))
    loop.run_forever()
