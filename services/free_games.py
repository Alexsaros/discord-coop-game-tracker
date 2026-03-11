import discord
from discord.ext.commands import Bot

from apis.discord import get_discord_user
from apis.free_games import get_free_to_keep_games
from shared.logger import send_error_message
from database.db import db_session_scope
from database.models.free_game import FreeGame
from database.models.free_game_subscriber import FreeGameSubscriber


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


async def set_user_free_game_notifications(bot: Bot, user_id: int, notify: bool):
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
