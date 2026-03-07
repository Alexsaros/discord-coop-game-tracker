import discord
from discord.ext.commands import Bot

from apis.discord import get_discord_user
from apis.free_games import get_free_to_keep_games
from logger import send_error_message
from storage.db import db_session_scope
from storage.free_game import FreeGame
from storage.free_game_subscriber import FreeGameSubscriber


async def check_free_to_keep_games(bot: Bot):
    try:
        with db_session_scope() as db_session:
            # Get the deals that we've already gotten earlier
            free_games_old = db_session.query(FreeGame).all()   # type: list[FreeGame]
            free_games_old_ids = [free_game.deal_id for free_game in free_games_old]

        free_games = await get_free_to_keep_games(bot)
        for free_game in free_games:
            # If this deal is new, send a message to users who want to be notified
            if free_game.deal_id not in free_games_old_ids:
                await notify_users_free_to_keep_game(bot, free_game)

    except Exception as e:
        await send_error_message(bot, e)


async def notify_users_free_to_keep_game(bot: Bot, free_game: FreeGame):
    with db_session_scope() as db_session:
        # Get the users that want to be notified of free games
        subscribed_users = db_session.query(FreeGameSubscriber).all()  # type: list[FreeGameSubscriber]

    for subscriber in subscribed_users:
        user = await get_discord_user(bot, subscriber.user_id)
        formatted_message = free_game.to_markdown()
        try:
            await user.send(formatted_message)
        except discord.Forbidden:
            # User has disabled DMs from the bot
            pass
