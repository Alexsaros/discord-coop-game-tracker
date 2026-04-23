import os

import requests
from discord.ext.commands import Bot
from dotenv import load_dotenv

from dateutil import parser
from shared.error_reporter import send_error_message
from database.db import db_session_scope
from database.models.free_game import FreeGame, GameType

load_dotenv()

ITAD_API_KEY = os.getenv("ITAD_API_KEY")
ITAD_DEALS_ENDPOINT = "https://api.isthereanydeal.com/deals/v2"


async def get_free_to_keep_games(bot: Bot) -> list[FreeGame]:
    params = {
        "key": ITAD_API_KEY,
        "filter": "N4IgDgTglgxgpiAXKAtlAdk9BXANrgGhBQEMAPJABgF9qg",     # Only free games (up to 0 euro)
        "mature": True,
    }

    # TODO use aiohttp
    response = requests.get(ITAD_DEALS_ENDPOINT, params=params)
    try:
        response.raise_for_status()
    except Exception as e:
        await send_error_message(bot, f"Failed to get free-to-keep games. {e}")
        return []

    payload = response.json()
    if payload["hasMore"] is True:
        await send_error_message(bot, "Warning: not all free-to-keep games fit in the response.")

    with db_session_scope() as db_session:
        # Empty the free games table
        db_session.query(FreeGame).delete()

        free_games = []
        game_deals_list = payload["list"]
        for game_deal in game_deals_list:
            deal_info = game_deal["deal"]
            expiry_datetime = parser.isoparse(deal_info["expiry"]) if deal_info["expiry"] else None
            game_type = GameType(game_deal["type"]) if game_deal["type"] else None
            # Save info on this deal in a new FreeGameData object
            free_game = FreeGame(
                deal_id=game_deal["id"],
                game_name=game_deal["title"],
                shop_name=deal_info["shop"]["name"],
                expiry_datetime=expiry_datetime,
                url=deal_info["url"],
                type=game_type,
            )

            free_games.append(free_game)
            db_session.add(free_game)

    return free_games
