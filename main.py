import os
import threading
import traceback
from collections import defaultdict
from typing import Optional

import discord
import asyncio
import time
import requests
import re
import datetime
import subprocess
import flask
import shutil
from io import BytesIO
from discord.ext import commands
from discord.ext.commands import CommandInvokeError
from discord.ui import View, Button, Select
from dotenv import load_dotenv
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import random
import hmac
import hashlib

from sqlalchemy.orm import joinedload, Session

import logger
from apis.discord import get_discord_user
from constants import EMBED_MAX_CHARACTERS, EMBED_DESCRIPTION_MAX_CHARACTERS, EMBED_MAX_FIELDS
from libraries import codenames
from logger import log
from services.free_games import check_free_to_keep_games
from database.models.bedtime import Bedtime
from database.db import db_session_scope, update_db
from database.models.free_game_subscriber import FreeGameSubscriber
from database.models.free_game import FreeGame
from database.models.game import Game, ReleaseState
from database.models.live_message import LiveMessageType, LiveMessage
from database.models.server import Server
from database.models.server_member import ServerMember
from database.models.user import User
from database.models.game_user_data import GameUserData

load_dotenv()
APP_ID = os.getenv("APP_ID")
PUBLIC_KEY = os.getenv("PUBLIC_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
STEAM_API_KEY = os.getenv("STEAM_API_KEY")
GITHUB_WEBHOOK_SECRET_TOKEN = os.getenv("GITHUB_WEBHOOK_SECRET_TOKEN")

DATABASE_FILE = "database/bot_data.db"
BEDTIME_MP3 = "bedtime.mp3"
BACKUP_DIRECTORY = "backups"
MAX_BACKUPS = 20

BEDTIME_LATE_INTERVAL_MINUTES = 15
EDIT_GAME_EMBED_COLOR = discord.Color.dark_blue()
LIST_EMBED_COLOR = discord.Color.blurple()
AFFINITY_EMBED_COLOR = discord.Color.purple()
TAROT_EMBED_COLOR = discord.Color.gold()
HOROSCOPE_EMBED_COLOR = discord.Color.magenta()
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

TAROT_CARDS = {
    "0": {
        "number": 0,
        "name": "The Fool",
        "meaning_upright": "It’s time for a new adventure, but there is a level of risk. Consider your options carefully, and when you are sure, take that leap of faith.",
        "meaning_reversed": " Beware false promises and naïveté. Don’t lose touch with reality.",
    },
    "1": {
        "number": 1,
        "name": "The Magician",
        "meaning_upright": "It’s time for action - your travel plans, business and creative projects are blessed. You have the energy and wisdom you need to make it happen now. Others see your talent.",
        "meaning_reversed": "False appearances. A scheme or project you’re involved in doesn’t ring true. A further meaning is a creative block, and travel plans being put on hold.",
    },
    "2": {
        "number": 2,
        "name": "The High Priestess",
        "meaning_upright": "Your dreams and your intuition provide the answers you need. This is a psychic card, revealing that truth comes from unconventional sources. You may find a wonderful course, guide or advisor at this time.",
        "meaning_reversed": "You may be let down by an authority figure pro other person you trust; there’s a side to this situation that has been covered up - until now.",
    },
    "3": {
        "number": 3,
        "name": "The Empress",
        "meaning_upright": "Enjoy this productive, joyful time when you’ll have the energy to develop your projects, decorate your home, spend time with children, and give yourself a little luxury. Money flows and love grows under The Empress’s influence.",
        "meaning_reversed": "Household problems, lack of time and money, and even a difficult older woman are the meanings of the Empress reversed. Hold on - things will improve if you keep calm.",
    },
    "4": {
        "number": 4,
        "name": "The Emperor",
        "meaning_upright": "Help, protection and the influence of a powerful individual for whom action speaks louder than words. Tradition is the watchword of The Emperor, so this is a time to play by the rules rather than flout convention.",
        "meaning_reversed": "Disorder; a controlling boss or older relative, poor leadership at work, bullying and upset in relationships. This person may oppose you, but view this as an opportunity to assert your own values.",
    },
    "5": {
        "number": 5,
        "name": "The Hierophant",
        "meaning_upright": "The Hierophant stands for unity. In your everyday life, he shows you committing to your goals so they become reality; you take action rather than daydream. He’s also a symbol of education, asking you to know yourself more deeply and to be open to new wisdom.",
        "meaning_reversed": "Perfectionism, self-criticism, and chaos in communities and at home. Projects become blocked due to miscommunication. If possible, step back and redefine what you alone want, regardless of others.",
    },
    "6": {
        "number": 6,
        "name": "The Lovers",
        "meaning_upright": "There’s amazing potential for lasting love, or reward, but you’ll need to make a mature choice that takes into account long-term rather than short-term benefits. Consider your future rather than old attitudes that don’t serve you.",
        "meaning_reversed": "Choosing the easier option under pressure and in relationships, feeling betrayed or let down by a partner. Don’t sacrifice your needs to keep the peace; put yourself first, even if that means walking away.",
    },
    "7": {
        "number": 7,
        "name": "The Chariot",
        "meaning_upright": "It’s time to take charge and move on. This may be a physical journey, or progress in work, relationships and projects. The Chariot often arrives in a reading after a major decision prompted by cards such as The Lovers, Judgement or The Moon.",
        "meaning_reversed": "Journeys and projects are delayed; a wrong turning. Recheck your plans and pay attention to detail you can fix. There’s arrogance around just now, too.",
    },
    "8": {
        "number": 8,
        "name": "Strength",
        "meaning_upright": "There’s tension around as you will have to keep strong-minded individuals - or your own urges - in check. Hold your space, be patient, and you’ll succeed with grace. An additional meaning is balance masculine and feminine qualities.",
        "meaning_reversed": "Avoiding facing an opponent; hiding from a challenge you could learn from. Your intuition knows not to shy away; it’s time to step up and turn the lion into a pussycat.",
    },
    "9": {
        "number": 9,
        "name": "The Hermit",
        "meaning_upright": "The need to think and heal the past; an opportunity to know yourself more deeply and find the strength and wisdom within. This is a path you choose, and you are alone, not lonely.",
        "meaning_reversed": "Isolation due to stubbornness; a turning away from support through fear. If you’re tired of being alone, reach out a little.",
    },
    "10": {
        "number": 10,
        "name": "Wheel of Fortune",
        "meaning_upright": "A change for the better. Blocks to progress dissolve quickly as events move on, so be open to whatever positive change comes. Look to the future.",
        "meaning_reversed": "The end of a negative cycle of events; you’re almost through the bad times, ready to move on to brighter possibilities.",
    },
    "11": {
        "number": 11,
        "name": "Justice",
        "meaning_upright": "A situation is resolved, ending a period of uncertainty. This card often heralds the end of a legal matter, but in general terms it predicts balance - so harmony is restored - and success, too.",
        "meaning_reversed": "Injustice; a decision goes against you. Keep the faith and seek out people who understand your position; turn away from those who seek to manipulate the situation for their own ends.",
    },
    "12": {
        "number": 12,
        "name": "The Hanged Man",
        "meaning_upright": "Delay. Waiting for change is frustrating, but it does allow you time to see a situation from a different perspective and devise new creative ways forward. An additional meaning is making a sacrifice in order to move on.",
        "meaning_reversed": "Indecision and fantasy; a refusal to be practical and get things done. Procrastination wastes your time.",
    },
    "13": {
        "number": 13,
        "name": "Death",
        "meaning_upright": "Transformation and change. This card doesn’t mean physical death, rather a time of transition, when whatever is not needed for the future must be given up. He brings release from the past, and new beginnings and opportunities.",
        "meaning_reversed": "Hanging onto the past; a refusal to leave the past alone.",
    },
    "14": {
        "number": 14,
        "name": "Temperance",
        "meaning_upright": "Balancing opposites; completing a multitude of tasks at once, which tests your skills and patience. If you can keep every plate spinning, others will see just how resourceful you are. An additional meaning is an opportunity to heal past issues.",
        "meaning_reversed": "Difficult memories; the past dominating the present. Ignoring debts and demands that need attention.",
    },
    "15": {
        "number": 15,
        "name": "The Devil",
        "meaning_upright": "Control issues; being in a relationship or other commitment that enslaves you. This is your perception, borne from obligation, guilt or fear. You can choose to walk away at any time. An additional meaning is struggle with addiction.",
        "meaning_reversed": "Manipulation and entrapment; an influence you find hard to resist, or one that repeats - you leave, return and leave again.",
    },
    "16": {
        "number": 16,
        "name": "The Tower",
        "meaning_upright": "Sudden endings that feel senseless and unnecessary wake you up to the fact that none of us is in control of the universe. This destruction illuminates the hidden tension holding together an aspect of your life; let it go.On a mundane level, The Tower also represents migraine attack.",
        "meaning_reversed": "Overthinking past events and apportioning blame. Don’t ruminate on the past - there is no fault.",
    },
    "17": {
        "number": 17,
        "name": "The Star",
        "meaning_upright": "Guidance, hope and inspiration; a time to nurture your talents and express your feelings. You are on the right path.",
        "meaning_reversed": "Living in a dream world, or a person full of ideas they can’t make happen just now. You may need to revise your expectations - it’s time for a reality-check.",
    },
    "18": {
        "number": 18,
        "name": "The Moon",
        "meaning_upright": "A difficult choice. You may doubt what’s on offer and feel you can’t see a clear picture. Take your time to listen to your inner voice; you don’t need to give in to pressure to make a decision. Intuition rather than reason will light the way.",
        "meaning_reversed": "Avoiding emotional issues; feeling disillusioned and unsafe. It may be risky, but it’s better to take a chance rather than do nothing.",
    },
    "19": {
        "number": 19,
        "name": "The Sun",
        "meaning_upright": "Happiness, protection and joy; a successful phase. A carefree time when old worries disappear. A further meaning is good health and renewed energy.",
        "meaning_reversed": "Frustration due to delayed plans, and holidays and projects may go on hold for a while, but don’t be downhearted - everything will get quickly back on track.",
    },
    "20": {
        "number": 20,
        "name": "Judgement",
        "meaning_upright": "Reviewing the past; deciding if it’s worth reconsidering a decision or situation. You’re in the process of judging yourself, too, musing on your past actions and relationships.",
        "meaning_reversed": "Guilt and worry may keep you tethered to the past. While it’s important to look back before you move on, there’s only so much soul-searching you, or someone close to you, can do.",
    },
    "21": {
        "number": 21,
        "name": "The World",
        "meaning_upright": "A successful conclusion before the beginning of a bright new phase; the world is opening up to you. You’re also rewarded with love, new opportunities and even gifts. A further meaning is peace and optimism.",
        "meaning_reversed": "An opportunity denied; you may feel your options are limited just now, but be patient - your time to travel and encounter exciting new opportunities will come.",
    },
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


class BotException(Exception):

    message = ""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class GameNotFoundException(BotException):
    pass


class InvalidArgumentException(BotException):
    pass


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

scheduler = AsyncIOScheduler(
    job_defaults={
        'misfire_grace_time': 3600,     # 1 hour
    }
)


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
    guild = get_discord_guild_object(server_id)
    if guild is None:
        return None

    with db_session_scope() as db_session:
        games = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.finished.is_(False))
                .all()
        )   # type: list[Game]

        # TODO get member count from database
        members = [member for member in guild.members if not member.bot]
        sorted_games = sort_games_by_score(games, len(members))

        games_list = []     # type: list[str]
        for game, score in sorted_games:
            # Get everyone who hasn't voted yet
            non_voters_ids = [member.id for member in members]

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


def generate_hog_embed(server_id: int):
    guild = get_discord_guild_object(server_id)
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

        # TODO get member count from database
        members = [member for member in guild.members if not member.bot]
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


def get_discord_guild_object(server_id: int) -> Optional[discord.Guild]:
    """
    Gets Discord's guild object for the given server ID.
    Returns None if not found.
    """
    # Get the Discord server object
    guild_object = bot.get_guild(server_id)
    if guild_object is None:
        log(f"Discord could not find guild with ID {server_id}.")
        return None
    return guild_object


async def get_live_message_object(server_id: int, message_type: LiveMessageType) -> Optional[discord.Message]:
    """
    Gets the message object for one of the live updating messages.
    Returns None if not found.
    """
    # Get the Discord guild object
    guild_object = get_discord_guild_object(server_id)
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

    updated_hog_embed = generate_hog_embed(server_id)
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


def get_steam_game_data(steam_game_id: int):
    # Check if an actual Steam game ID was given
    if steam_game_id is None:
        return None
    steam_game_id = str(steam_game_id)

    # API URL for getting info on a specific Steam game
    url = f"https://store.steampowered.com/api/appdetails?appids={steam_game_id}&cc=eu"

    params = {
        "appids": steam_game_id,
        "cc": "nl",     # Country used for pricing/currency
        "l": "english",
    }
    response = requests.get(url, params=params)

    if response.status_code >= 300:
        log(f"Failed to get game with ID \"{steam_game_id}\" using Steam API: {response.status_code}")
        log(response.json())
        return None

    response_json = response.json()
    steam_game_data = response_json.get(steam_game_id, {}).get("data", {})
    if not steam_game_data:
        log(f"Warning: missing Steam info for Steam game ID {steam_game_id}: {response_json}")
        return None

    return steam_game_data


async def get_game_price(steam_game_id: int):
    """
    Uses the Steam API to search for info on the given Steam game ID.
    Returns a dictionary containing the "id", "price_current" and "price_original" keys.
    Returns None if the game wasn't found.
    """
    steam_game_data = get_steam_game_data(steam_game_id)
    if steam_game_data is None:
        return None

    game_name = steam_game_data["name"]

    price_current = -1
    price_original = -1
    price_overview = steam_game_data.get("price_overview", {})
    if not price_overview:
        # Check if the game has already been released
        unreleased = steam_game_data.get("release_date", {}).get("coming_soon", False)
        if unreleased:
            price_current = -2
            price_original = -2
        else:
            # Sanity check to see if the game is really free
            if not "is_free":
                log(f"Warning: is_free is False, but missing price_overview for game {game_name}.")
            else:
                price_current = 0
                price_original = 0
    else:
        price_currency = price_overview["currency"]
        if price_currency != "EUR":
            await send_error_message(f"Error: received currency {price_currency} for game {game_name}.")
        else:
            price_current = price_overview["final"] / 100
            price_original = price_overview["initial"] / 100

    steam_info = {
        "id": steam_game_data["steam_appid"],
        "price_current": price_current,
        "price_original": price_original,
    }

    return steam_info


def get_steam_game_banner(steam_game_id):
    """
    Uses the Steam API to download the banner of the given Steam game ID, and upload it to Discord.
    Returns a Discord File object.
    Returns None if the game wasn't found.
    """
    steam_game_data = get_steam_game_data(steam_game_id)
    if steam_game_data is None:
        return None
    game_name = steam_game_data.get("name", "")

    # Fetch the banner
    banner_url = steam_game_data.get("header_image")
    if banner_url is None:
        return None
    response = requests.get(banner_url)
    if response.status_code >= 300:
        log(f"Failed to get banner for Steam game ID \"{steam_game_id}\" using Steam API: {response.status_code}")
        log(response.json())
        return None

    # Convert the banner to a Discord File and return it
    image_bytes = BytesIO(response.content)
    return discord.File(image_bytes, f"{game_name} banner.jpg")


async def update_database_steam_prices():
    with db_session_scope() as db_session:
        games = db_session.query(Game).all()    # type: list[Game]
        for game in games:
            steam_game_info = await get_game_price(game.steam_id)
            if steam_game_info is not None:
                game.price_current = steam_game_info["price_current"]
                game.price_original = steam_game_info["price_original"]

    log("Retrieved Steam prices")

    await update_all_lists()


def search_steam_for_game(game_name):
    """
    Uses the Steam API to search for the given game.
    Returns a dictionary retrieved from the Steam API matching the given game.
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

    return game_match


def parse_boolean(boolean_string):
    boolean_string_lower = boolean_string.lower()
    if boolean_string_lower[:1] in ["y", "t"]:
        return True
    elif boolean_string_lower[:1] in ["n", "f"]:
        return False
    else:
        raise InvalidArgumentException(f"Received invalid argument ({boolean_string}). Must be either \"yes\" or \"no\".")


def load_bedtime_scheduler_jobs():
    with db_session_scope() as db_session:
        bedtimes = db_session.query(Bedtime).all()  # type: list[Bedtime]

    for bedtime in bedtimes:
        # Re-schedule each bedtime job
        hour = bedtime.bedtime_time.hour
        minute = bedtime.bedtime_time.minute
        scheduler.add_job(play_bedtime_audio, CronTrigger(hour=hour, minute=minute), args=[bedtime.user_id, bedtime.server_id], id=bedtime.scheduler_job_id)

        # Re-schedule the late bedtime reminder as well
        bedtime_late_job_id = bedtime.scheduler_job_late_id
        bedtime_original = datetime.datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        bedtime_late = bedtime_original + datetime.timedelta(minutes=BEDTIME_LATE_INTERVAL_MINUTES)
        hour_late = bedtime_late.hour
        minute_late = bedtime_late.minute
        scheduler.add_job(play_bedtime_audio, CronTrigger(hour=hour_late, minute=minute_late), args=[bedtime.user_id, bedtime.server_id, True], id=bedtime_late_job_id)


async def load_views():
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
    scheduler.start()

    # Load scheduled jobs that were saved during earlier runs
    load_bedtime_scheduler_jobs()

    codenames.load_games(bot)

    log("Finished on_connect()")


@bot.event
async def on_ready():
    log(f"{bot.user} has connected to Discord!")

    # Make buttons functional
    await load_views()

    # Checks Steam and displays the updated prices
    await update_database_steam_prices()
    # Check any free-to-keep games
    await check_free_to_keep_games(bot)

    # Create a job to update the prices every 6 hours
    scheduler.add_job(update_database_steam_prices, CronTrigger(hour="0,6,12,18"))
    # Create a job to check for new free-to-keep games every 6 hours
    scheduler.add_job(check_free_to_keep_games, CronTrigger(hour="7,19"), args=[bot])
    # Create a job that makes a backup of the dataset every 12 hours
    scheduler.add_job(create_backup, CronTrigger(hour="2,14"))
    # Create a job that removes old Codenames games every day
    scheduler.add_job(codenames.clean_up_old_games, CronTrigger(hour="18"), args=[bot])

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

    await update_database_steam_prices()

    await update_live_messages(server_id)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
            game = get_game(db_session, server_id, game_name)   # TODO handle case when the game is already finished
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
            game_price = await get_game_price(game.steam_id)
            if game_price is not None:
                game.price_current = game_price["price_current"]
                game.price_original = game_price["price_original"]

        db_session.add(game)

    await update_live_messages(server_id)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="remove", help="Removes a game from the list. Example: !remove \"game name\".")
async def remove_game(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        # Remove the game from the database
        db_session.delete(game)

    await update_live_messages(server_id)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="hog", help=":boar:")
async def hall_of_game(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    hog_embed = generate_hog_embed(ctx.guild.id)
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

    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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

    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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

        # TODO get member count from database
        members = [member for member in ctx.guild.members if not member.bot]
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

    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="owned_games", help="Displays a list of games that everyone has marked as owned. Example: !owned_games.")
async def display_owned_games(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        # TODO get member count from database
        members = [member for member in ctx.guild.members if not member.bot]
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

    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="edit", help="Displays the given game as a message to be able edit it using its reactions. Example: !edit \"game name\".")
async def edit(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

    edit_game = EditGame(game.server_id, game.id, ctx.channel.id)
    await edit_game.send_message()

    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="local", help="Sets whether a game can be played together with one copy. Example: !local \"game name\" no. Defaults to \"yes\".")
async def set_local(ctx, game_name, is_local="yes"):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    local = parse_boolean(is_local)

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        game.local = local

    await update_live_messages(server_id)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
        steam_game_info = await get_game_price(steam_id)
        # Default to no price if the Steam game couldn't be found
        game.price_current = None
        game.price_original = None
        if steam_game_info is not None:
            game.price_current = steam_game_info["price_current"]
            game.price_original = steam_game_info["price_original"]

    await update_live_messages(server_id)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="alias", help="Sets an alias for yourself, to be displayed in the overview. Example: !alias :sunglasses:. Leave empty to clear it.")
async def set_alias(ctx, new_alias=None):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    with db_session_scope() as db_session:
        server_member = db_session.get(ServerMember, (user_id, server_id))  # type: ServerMember

        server_member.alias = new_alias

    await update_live_messages(server_id)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="rename", help="Change the name of a game. Example: !rename \"game name\" \"new game name\".")
async def rename_game(ctx, game_name, new_game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        game.name = new_game_name

    await update_live_messages(server_id)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="send_me_free_games", help="Opt in or out of receiving a message when a game is free to keep. Example: !send_me_free_games no. Defaults to \"yes\".")
async def send_me_free_games(ctx, notify_on_free_game="yes"):
    log(f"{ctx.author}: {ctx.message.content}")
    user_id = ctx.author.id

    notify = parse_boolean(notify_on_free_game)

    with db_session_scope() as db_session:
        free_game_subscriber = db_session.get(FreeGameSubscriber, user_id)  # type: FreeGameSubscriber
        if not notify:
            if free_game_subscriber is not None:
                db_session.delete(free_game_subscriber)
        else:
            if free_game_subscriber is None:
                free_game_subscriber = FreeGameSubscriber(
                    user_id=user_id,
                )
                db_session.add(free_game_subscriber)

            # Notify the interested user about all of the currently active deals
            user = await get_discord_user(bot, user_id)
            await user.send("From now on, I will send you a message whenever a game becomes free to keep.")

            free_games = db_session.query(FreeGame).all()   # type: list[FreeGame]
            for free_game in free_games:
                formatted_message = free_game.to_markdown()
                await user.send(formatted_message)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


def get_users_voice_channel(user_id: int, server_id: int):
    """
    Returns the voice channel the user is in, or None if they're not in a voice channel or could not be found.
    """
    guild = get_discord_guild_object(server_id)
    if guild is None:
        return None

    user = guild.get_member(user_id)    # type: discord.Member
    if user is None:
        log(f"No user with ID {user_id} found.")
        return None

    if user.voice is None or user.voice.channel is None:
        log(f"User with ID {user_id} is not in a voice channel.")
        return None

    return user.voice.channel


async def play_audio(voice_channel: discord.VoiceChannel, audio_path):
    try:
        voice_client = await voice_channel.connect()
    except Exception as e:
        await send_error_message(f"Error: failed to connect to voice channel. {e}")
        return

    try:
        # Wait a little to give the "joined channel" sound effect time to go away before we start playing sound
        await asyncio.sleep(0.5)
        voice_client.play(discord.FFmpegPCMAudio(audio_path))

        while voice_client.is_playing():
            await asyncio.sleep(1)
    except Exception as e:
        await send_error_message(f"Error: failed to play audio. {e}")

    await voice_client.disconnect()


async def play_bedtime_audio(user_id: int, server_id: int, late_reminder: bool = False):
    voice_channel = get_users_voice_channel(user_id, server_id)
    if voice_channel is None:
        return

    user_specific_bedtime_mp3 = f"bedtime_"
    if late_reminder:
        user_specific_bedtime_mp3 += "late_"
    user_specific_bedtime_mp3 += f"{user_id}.mp3"

    # If the user has a unique bedtime mp3, play that
    if os.path.isfile(user_specific_bedtime_mp3):
        await play_audio(voice_channel, user_specific_bedtime_mp3)
    else:
        if late_reminder:
            # If the user has not set an mp3 for the late reminder, do not play anything
            return
        else:
            # User has not set an mp3, so play the generic mp3
            await play_audio(voice_channel, BEDTIME_MP3)


@bot.command(name="bedtime", help="Sets a reminder for your bedtime (CET). Example: !bedtime 21:30.")
async def set_bedtime(ctx, bedtime):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    try:
        bedtime_split = bedtime.split(":")
        hour = int(bedtime_split[0])
        minute = 0 if len(bedtime_split) == 1 else int(bedtime_split[1])
        assert hour < 24
        assert minute < 60
    except (ValueError, IndexError, AssertionError):
        await ctx.send("Invalid time given.")
        return

    with db_session_scope() as db_session:
        bedtime_old = db_session.get(Bedtime, (user_id, server_id))    # type: Bedtime

        # First stop any existing bedtimes for this user
        if bedtime_old is not None:
            try:
                scheduler.remove_job(bedtime_old.scheduler_job_id)
            except JobLookupError as e:
                await send_error_message(f"Error! Unable to remove scheduled bedtime job with id {bedtime_old.scheduler_job_id}. {e}")
            try:
                scheduler.remove_job(bedtime_old.scheduler_job_late_id)
            except JobLookupError as e:
                await send_error_message(f"Error! Unable to remove scheduled late bedtime job with id {bedtime_old.scheduler_job_late_id}. {e}")

        # If a negative value was given, remove the bedtime alarm
        if hour < 0 or minute < 0:
            if bedtime_old is not None:
                db_session.delete(bedtime_old)
        else:
            # Schedule the new bedtime
            job = scheduler.add_job(play_bedtime_audio, CronTrigger(hour=hour, minute=minute),
                                    args=[user_id, server_id], id=f"{server_id}_bedtime_{user_id}")

            # Also schedule a later reminder
            bedtime_original = datetime.datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
            bedtime_late = bedtime_original + datetime.timedelta(minutes=BEDTIME_LATE_INTERVAL_MINUTES)
            hour_late = bedtime_late.hour
            minute_late = bedtime_late.minute
            job_late = scheduler.add_job(play_bedtime_audio, CronTrigger(hour=hour_late, minute=minute_late),
                                         args=[user_id, server_id, True], id=f"{server_id}_bedtime_late_{user_id}")

            # Save the new bedtime
            bedtime_new = Bedtime(
                user_id=user_id,
                server_id=server_id,
                bedtime_time=datetime.time(hour=hour, minute=minute),
                scheduler_job_id=job.id,
                scheduler_job_late_id=job_late.id,
            )
            db_session.add(bedtime_new)

    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="tarot", help="Draws a major arcana tarot card. Example: !tarot.")
async def tarot(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    username = str(ctx.author)

    # Draw a random card
    card_key = random.choice(list(TAROT_CARDS.keys()))
    card_dict = TAROT_CARDS[card_key]
    card_name = card_dict["name"]
    is_reversed = random.choice([True, False])
    card_position = "(Reversed)" if is_reversed else "(Upright)"

    # Get the image and create a Discord File object
    image_filename = f"{card_key}-{card_name.lower().replace(' ', '-')}"
    image_filename += "-reversed.jpg" if is_reversed else ".jpg"
    image_path = os.path.join("tarot-cards", image_filename)
    file = discord.File(image_path, filename=image_filename)

    # Create the embed
    title = f"{username} pulled tarot card: {card_name} {card_position}"
    interpretation = card_dict["meaning_reversed"] if is_reversed else card_dict["meaning_upright"]
    tarot_embed = discord.Embed(
        title=title,
        description=interpretation,
        color=TAROT_EMBED_COLOR
    )

    await ctx.send(embed=tarot_embed, file=file)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="horoscope", help="Divines your daily horoscope. Example: !horoscope.")
async def horoscope(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    username = str(ctx.author)

    # Create a seed based on the user's name and today's date
    seed = hash(f"{username}{datetime.date.today()}")
    # Use the seed for random number generation
    rng = random.Random(seed)

    THINGS = ["destiny", "puppies", "the weather", "the supernatural", "liveliness", "death", "wealth", "unreasonable demands",
              "adventure", "bad luck", "good luck", "change", "disaster", "challenges", "unexpected news", "opportunities", "strong emotions",
              "punishment", "short breaks", "taxes", "happiness", "new relationships", "an unexpected gift", "secrets",
              "destiny", "revelations", "the unknown", "fortune", "a turning point", "nature", "life", "personal growth", "a chance encounter",
              "Jo", "Alex", "Rento", "Remi"]
    if username == "remitoid":
        THINGS.remove("Remi")
    elif username == "alexsaro":
        THINGS.remove("Alex")
    elif username == "rento247":
        THINGS.remove("Rento")
    elif username == "jo.bear":
        THINGS.remove("Jo")

    PREDICTIONS_PRE = ["must be cautious of", "would do well to avoid", "can expect", "might encounter", "would benefit from being accepting of",
                       "must not be receptive to", "can not avoid", "will be delighted by", "will be doomed by", "might be taken aback by",
                       "will experience", "could be pleasantly surprised by", "may find yourself dealing with", "should keep an eye on"]
    WHERE = ["nearby", "close to you", "at your approximate location", "in your neighbourhood", "in your surroundings", "within reach",
             "under your bed", "where you least expect it", "somewhere close", "just around the corner", "at a place you hold dear",
             "in nature", "all around you", "on your daily commute", "on your next journey", "in a hidden location", "in crowded areas",
             "on a quiet street", "in your dreams", "amidst chaos", "in technology", "out there"]
    PREDICTIONS_POST = ["will find you", "will help you out", "might cause problems", "could appear", "will change things up",
                        "could distract you from your goal", "will be absent", "might offer a unique chance", "may disappear"]
    TIMES = ["before you know it", "when Mercury is in retrograde", "when you least expect it", "at an inopportune moment",
             "in your hour of need", "at a moment of peace", "during unusual events", "at mealtime", "while you're out", "while you're relaxing",
             "at just the right moment", "in the near future", "when the time is right", "when the opportunity arises"]
    ADVICE = ["my advice is to", "you would do best not to", "your future might change if you", "go forth and", "consider to",
              "be sure to", "it might be time to", "you'll find peace if you would", "try to", "do not hesitate to", "perhaps you should"]
    ACTIONS = ["go out and explore", "stay indoors", "take it easy", "be proactive", "reconsider things", "take advantage of new opportunities",
               "destroy your enemies", "chase your dreams", "take up a new hobby", "prepare for the worst", "start something new", "trust your instincts"]
    CONNECTORS = ["moreover", "additionally", "on top of that", "finally", "furthermore", "on another note"]

    sentence1 = f"You {rng.choice(PREDICTIONS_PRE)} {rng.choice(THINGS)} {rng.choice(WHERE)}."
    sentence2 = f"{rng.choice(CONNECTORS).capitalize()}, {rng.choice(THINGS)} {rng.choice(PREDICTIONS_POST)} {rng.choice(TIMES)}."
    sentence3 = f"{rng.choice(ADVICE).capitalize()} {rng.choice(ACTIONS)}."

    # Create the horoscope embed
    title = f"{username}'s horoscope :sparkles:"
    horoscope_text = f"{sentence1} {sentence2} {sentence3}"
    horoscope_embed = discord.Embed(
        title=title,
        description=horoscope_text,
        color=HOROSCOPE_EMBED_COLOR
    )

    await ctx.send(embed=horoscope_embed)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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

    answers = [
        "It is certain",
        "It is decidedly so",
        "Without a doubt",
        "Yes definitely",
        "You may rely on it",
        "As I see it, yes",
        "Most likely",
        "Outlook good",
        "Yes",
        "Signs point to yes",
        "Reply hazy, try again",
        "Ask again later",
        "Better not tell you now",
        "Cannot predict now",
        "Concentrate and ask again",
        "Don't count on it",
        "My reply is no",
        "My sources say no",
        "Outlook not so good",
        "Very doubtful",
    ]
    answer = f"The Magic 8 Ball says: *{random.choice(answers)}*."
    await ctx.send(answer)


@bot.command(name="choose", help="Randomly chooses one of the given options. Example: !choose red green \"light blue\".")
async def choose(ctx, *options):
    log(f"{ctx.author}: {ctx.message.content}")

    selected_option = random.choice(options)
    options_string = ", ".join(options)
    message_text = f"Possible options: {options_string}.\nChosen: **{selected_option}**."
    message = await ctx.send(message_text)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="roll", help="Performs the given dice rolls and shows the result. Example: !roll 2d8+3.")
async def roll_dice(ctx, expression):
    log(f"{ctx.author}: {ctx.message.content}")

    if not re.fullmatch(r"[\d+\-*/().d\s]+", expression):
        raise InvalidArgumentException(f"The entered dice rolls contains invalid characters.")

    # Ensure Discord doesn't try to parse the asterisks
    expression = expression.replace("*", "\\*")

    display_text = expression
    eval_expression = expression
    display_offset = 0
    eval_offset = 0

    for match in re.finditer(r"(\d+)d(\d+)", expression):
        amount, sides = map(int, match.groups())
        rolls = [random.randint(1, sides) for _ in range(amount)]

        rolls_text = "+".join(str(roll) for roll in rolls)
        rolls_text = f"`{rolls_text}`"  # Make results of individual dice rolls monospace

        start, end = match.start(), match.end()
        # Replace the dice roll with the results of the dice roll
        display_text = display_text[:start + display_offset] + rolls_text + display_text[end + display_offset:]
        # Keep track of how much the display string shifted in length compared to the original string
        display_offset += len(rolls_text) - (end - start)

        eval_string = str(sum(rolls))
        # Do the same for the eval string
        eval_expression = eval_expression[:start + eval_offset] + eval_string + eval_expression[end + eval_offset:]
        eval_offset += len(eval_string) - (end - start)

    # Remove backslashes and compute the result
    eval_expression = eval_expression.replace("\\", "")
    result = eval(eval_expression)

    message_text = f"{ctx.author.name} rolls: {expression}.\nResult: {display_text} = **{result}**.\n## **{result}**"
    message = await ctx.send(message_text)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="codenames", help="Start a Codenames game.")
async def start_codenames(ctx):
    log(f"{ctx.author}: {ctx.message.content}")

    await codenames.create_new_game(ctx)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


@bot.command(name="codenames_settings", help="Open the settings menu for Codenames.")
async def codenames_settings(ctx):
    log(f"{ctx.author}: {ctx.message.content}")

    await codenames.show_settings(ctx)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass


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
            # TODO check if it is possible they are a bot
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
