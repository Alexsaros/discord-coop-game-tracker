import os
import traceback

import discord
import asyncio
import time
import datetime
from discord.ext import commands
from discord.ext.commands import CommandInvokeError, guild_only, NoPrivateMessage
from dotenv import load_dotenv
from apscheduler.triggers.cron import CronTrigger
import random

from apis.igdb import get_multiplayer_info_from_igdb, MultiplayerInfo
from apis.steam import get_steam_game_price, get_steam_game_banner, search_steam_for_game, update_database_steam_prices, \
    update_game_steam_prices_fields
from apis.steam_web import get_steam_user_id, get_owned_steam_games, update_database_games_with_steam_user_data, \
    update_database_game_user_data
from database.backup_service import create_backup
from database.utils import get_game, get_user_by_name, get_server_members
from embeds.affinity import generate_affinity_embed
from embeds.edit_game import EditGame
from embeds.hall_of_game import generate_hog_embed
from embeds.list import generate_list_embeds, generate_unvoted_embed
from embeds.list_view import ListView
from embeds.owned_games import generate_owned_games_embed
from embeds.play_without import generate_play_without_embed
from embeds.unvoted_games import UnvotedGames
from libraries.critters.critters import start_critters_game
from services.bedtime import load_bedtime_scheduler_jobs
from services.help import CustomHelpCommand
from shared import error_reporter
from apis.discord import delete_message
from libraries import codenames
from shared.exceptions import BotException, GameNotFoundException, NoAccessException
from shared.live_messages import update_all_lists, load_list_views, update_live_messages, get_live_message_object, \
    update_list, update_hall_of_game
from shared.logger import log
from services import dice_roller, bedtime
from services.eight_ball import use_eight_ball
from services.free_games import check_free_to_keep_games, set_user_free_game_notifications
from database.db import db_session_scope, update_db
from database.models.game import Game
from database.models.live_message import LiveMessageType, LiveMessage
from database.models.server import Server
from database.models.server_member import ServerMember
from database.models.user import User
from database.models.game_user_data import GameUserData
from services.horoscope import create_horoscope_embed
from services.tarot.tarot import create_random_tarot_embed
from shared.scheduler import get_scheduler
from shared.utils import parse_boolean
from bot_updater import start_listening_to_updates
from embeds.page_buttons_view import PageButtonsView

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True


bot = commands.Bot(command_prefix="!", intents=intents, help_command=CustomHelpCommand())


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


@guild_only()
@bot.command(name="update_prices", help="Retrieves the latest prices from Steam. Example: !update_prices.")
async def update_prices(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    await update_steam_prices()

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
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
            update_game_steam_prices_fields(game, game_price)

        # If this game has a Steam ID, for each user with a Steam ID, check if they have owned or played the game
        if game.steam_id:
            members = (
                db_session.query(ServerMember)
                    .filter(ServerMember.server_id == server_id)
                    .filter(ServerMember.steam_id.isnot(None))
                    .all()
            )   # type: list[ServerMember]
            for member in members:
                try:
                    owned_games = await get_owned_steam_games(member.steam_id)
                    update_database_game_user_data(db_session, server_id, game.id, member.user_id, game.steam_id, owned_games)
                except NoAccessException as e:
                    await ctx.send(e.message)

        # Get multiplayer info from IGDB
        multiplayer_info = await get_multiplayer_info_from_igdb(bot, game_name)   # type: MultiplayerInfo
        if multiplayer_info is not None:
            if multiplayer_info.max_players_online > 0:
                game.player_count = multiplayer_info.max_players_online
            if multiplayer_info.max_players_offline > 0:
                game.local = True
                if multiplayer_info.max_players_online == 0:
                    game.player_count = multiplayer_info.max_players_offline
            if multiplayer_info.campaign_coop is False:
                if game.notes is None:
                    game.notes = []
                game.notes.append("No co-op campaign.")

        db_session.add(game)

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
@bot.command(name="remove", help="Removes a game from the list. Example: !remove \"game name\".")
async def remove_game(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        # Remove the game from the database
        db_session.delete(game)

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
@bot.command(name="finish", help="Marks a game as finished, moving it to the completed games list. Example: !finish \"game name\".")
async def finish_game(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        game.finished = True
        game.finished_timestamp = time.time()

        hog_message = await get_live_message_object(bot, server_id, LiveMessageType.HALL_OF_GAME)
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

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
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

    await update_hall_of_game(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
@bot.command(name="hog", help=":boar:")
async def hall_of_game(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    hog_embed = await generate_hog_embed(bot, ctx.guild.id)
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


@guild_only()
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

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
@bot.command(name="list", help="Displays a sorted list of all games. Example: !list.")
async def list_games(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    user_ids = [member.user_id for member in get_server_members(server_id)]

    list_embed = (await generate_list_embeds(bot, server_id, user_ids))[0]
    if list_embed is None:
        await ctx.send("No games registered for this server yet.")
        return
    embeds = [list_embed]
    unvoted_embed = generate_unvoted_embed(server_id)
    if unvoted_embed is not None:
        embeds.append(unvoted_embed)

    # Remove the buttons from the old list message
    list_message_old = await get_live_message_object(bot, server_id, LiveMessageType.LIST)
    if list_message_old is not None:
        await list_message_old.edit(embeds=embeds, view=None)

        with db_session_scope() as db_session:
            # Delete the old list message from the database
            list_live_message_old = db_session.get(LiveMessage, list_message_old.id)    # type: LiveMessage
            if list_live_message_old is not None:
                db_session.delete(list_live_message_old)

    list_message = await ctx.send(embeds=embeds)
    list_view = ListView(bot, list_embed.title, list_message.id, update_list, server_id)
    await list_message.edit(embeds=embeds, view=list_view)

    with db_session_scope() as db_session:
        list_live_message = LiveMessage(
            server_id=server_id,
            channel_id=list_message.channel.id,
            message_id=list_message.id,
            message_type=LiveMessageType.LIST,
            selected_user_ids=user_ids
        )
        db_session.add(list_live_message)

    await delete_message(ctx.message)


@guild_only()
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

    play_without_embed = generate_play_without_embed(server_id, user)

    await ctx.send(embed=play_without_embed)
    await delete_message(ctx.message)


@guild_only()
@bot.command(name="owned_games", help="Displays a list of games that everyone has marked as owned. Example: !owned_games.")
async def display_owned_games(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    owned_games_embed = generate_owned_games_embed(server_id)

    await ctx.send(embed=owned_games_embed)
    await delete_message(ctx.message)


@guild_only()
@bot.command(name="edit", help="Displays the given game as a message to be able edit it using its reactions. Example: !edit \"game name\".")
async def edit(ctx, game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

    edit_game = EditGame(bot, game.server_id, game.id, ctx.channel.id)
    await edit_game.send_message()

    await delete_message(ctx.message)


@guild_only()
@bot.command(name="unvoted", help="Shows you which games you haven't voted on yet. Example: !unvoted.")
async def unvoted(ctx):
    log(f"{ctx.author}: {ctx.message.content}")

    unvoted_games = UnvotedGames(bot, ctx.guild, ctx.author)
    await unvoted_games.send_message()

    await delete_message(ctx.message)


@guild_only()
@bot.command(name="add_note", help="Adds an informative note to a game. Example: !add_note \"game name\" \"PvP only\".")
async def add_note(ctx, game_name, note_text):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        game.notes.append(note_text)

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
@bot.command(name="remove_note", help="Removes a note from a game. Example: !remove_note \"game name\" \"PvP only\".")
async def remove_note(ctx, game_name, note_text):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        if note_text not in game.notes:
            await ctx.send(f"Game \"{game.name}\" does not have note \"{note_text}\".")
            return

        game.notes.remove(note_text)

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
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
        update_game_steam_prices_fields(game, steam_game_info)

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
@bot.command(name="alias", help="Sets an alias for yourself, to be displayed in the overview. Example: !alias :sunglasses:. Leave empty to clear it.")
async def set_alias(ctx, new_alias=None):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    with db_session_scope() as db_session:
        server_member = db_session.get(ServerMember, (user_id, server_id))  # type: ServerMember

        server_member.alias = new_alias

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
@bot.command(name="rename", help="Change the name of a game. Example: !rename \"game name\" \"new game name\".")
async def rename_game(ctx, game_name, new_game_name):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id

    with db_session_scope() as db_session:
        game = get_game(db_session, server_id, game_name)

        game.name = new_game_name

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
@bot.command(name="affinity", help="Shows how similarly you vote to other people. Example: !affinity.")
async def show_affinity(ctx):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    affinity_embed = generate_affinity_embed(server_id, user_id)

    await ctx.send(embed=affinity_embed)
    await delete_message(ctx.message)


@bot.command(name="send_me_free_games", help="Opt in or out of receiving a message when a game is free to keep. Example: !send_me_free_games no. Defaults to \"yes\".")
async def send_me_free_games(ctx, notify_on_free_game="yes"):
    log(f"{ctx.author}: {ctx.message.content}")
    user_id = ctx.author.id

    notify = parse_boolean(notify_on_free_game)
    await set_user_free_game_notifications(bot, user_id, notify)

    await delete_message(ctx.message)


@guild_only()
@bot.command(name="link_steam", help="Link your Steam account to automatically fetch owned and played games. Accepts a Steam profile ID or custom URL ID. Example: !link_steam 76561198071149263.")
async def link_steam_account(ctx, steam_profile_id):
    log(f"{ctx.author}: {ctx.message.content}")
    server_id = ctx.guild.id
    user_id = ctx.author.id

    try:
        steam_user_id = int(steam_profile_id)
    except ValueError:
        steam_user_id = await get_steam_user_id(steam_profile_id)

    owned_games = await get_owned_steam_games(steam_user_id)

    with db_session_scope() as db_session:
        server_member = db_session.get(ServerMember, (user_id, server_id))  # type: ServerMember

        # Save the Steam ID for this user in the database
        server_member.steam_id = steam_user_id

        update_database_games_with_steam_user_data(db_session, server_id, user_id, owned_games)

    await update_live_messages(bot, server_id)
    await delete_message(ctx.message)


@guild_only()
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


@guild_only()
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


@guild_only()
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


@bot.command(name="critters", help="Start a Critters game against another user or against Cooper (by not giving a username). Example: !critters alexsaro.")
async def critters(ctx, username: str = None):
    log(f"{ctx.author}: {ctx.message.content}")
    user_id = ctx.author.id

    opponent_user_id = None
    if username is not None:
        opponent_user = get_user_by_name(username)
        if opponent_user.id == user_id:
            await ctx.send("You can't play against yourself!")
            return

        opponent_user_id = opponent_user.id

    await start_critters_game(bot, user_id, opponent_user_id)

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
