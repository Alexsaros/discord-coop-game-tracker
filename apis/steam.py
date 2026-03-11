from io import BytesIO
from typing import Optional

import discord
import requests

from database.db import db_session_scope
from database.models import Game
from shared.logger import log


def get_steam_game_data(steam_game_id: int) -> Optional[dict]:
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


async def get_steam_game_price(steam_game_id: int) -> Optional[dict]:
    """
    Uses the Steam API to search for info on the given Steam game ID.
    Returns a dictionary containing the "id", "price_current" and "price_original" keys.
    Returns None if the game wasn't found.
    """
    steam_game_data = get_steam_game_data(steam_game_id)
    if steam_game_data is None:
        return None

    game_name = steam_game_data["name"]

    # TODO fix prices
    price_current = -1
    price_original = -1
    price_overview = steam_game_data.get("price_overview", {})
    if not price_overview:
        # Check if the game has already been released
        unreleased = steam_game_data.get("release_date", {}).get("coming_soon", False)
        if unreleased:
            # TODO
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


def get_steam_game_banner(steam_game_id: int) -> Optional[discord.File]:
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
            steam_game_info = await get_steam_game_price(game.steam_id)
            if steam_game_info is not None:
                game.price_current = steam_game_info["price_current"]
                game.price_original = steam_game_info["price_original"]

    log("Retrieved Steam prices")


def search_steam_for_game(game_name: str) -> Optional[dict]:
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