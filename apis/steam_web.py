import os

import aiohttp
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from database.models import Game, GameUserData
from shared.exceptions import ApiException, UserNotFoundException, NoAccessException

load_dotenv()

# Set Steam web API key via environment variables
STEAM_WEB_API_KEY = os.getenv("STEAM_WEB_API_KEY")

STEAM_RESOLVE_VANITY_URL_ENDPOINT = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1"
STEAM_GET_OWNED_GAMES_ENDPOINT = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1"

PLAYED_BEFORE_MINUTES_THRESHOLD = 120


class SteamGameInfo:

    def __init__(self, steam_game_info: dict) -> None:
        super().__init__()
        self.id = steam_game_info["appid"]  # type: int
        # Time played in minutes
        self.playtime = steam_game_info["playtime_forever"]     # type: int


async def get_steam_user_id(vanity_url: str) -> int:
    async with aiohttp.ClientSession() as session:
        params = {
            "key": STEAM_WEB_API_KEY,
            "vanityurl": vanity_url,
        }

        response = await session.get(STEAM_RESOLVE_VANITY_URL_ENDPOINT, params=params)
        try:
            response.raise_for_status()
        except Exception as e:
            raise ApiException(f"Failed to fetch Steam user ID. {e}", e)

        payload = await response.json()
        steam_user_id = payload.get("response", {}).get("steamid", None)    # type: int
        if steam_user_id is None:
            raise UserNotFoundException(f"Could not find Steam user <https://steamcommunity.com/id/{vanity_url}>.")

        return steam_user_id


async def get_owned_steam_games(steam_user_id: int) -> dict[int, SteamGameInfo]:
    async with aiohttp.ClientSession() as session:
        params = {
            "key": STEAM_WEB_API_KEY,
            "steamid": steam_user_id,
        }

        response = await session.get(STEAM_GET_OWNED_GAMES_ENDPOINT, params=params)
        if response.status == 400:
            raise UserNotFoundException(f"Could not find Steam user <https://steamcommunity.com/profiles/{steam_user_id}>.")
        try:
            response.raise_for_status()
        except Exception as e:
            raise ApiException(f"Failed to fetch games for Steam user ID. {e}", e)

        payload = await response.json()
        games = payload.get("response", {}).get("games", None)  # type: list
        if games is None:
            raise NoAccessException(f"Could not fetch any games for Steam user <https://steamcommunity.com/profiles/{steam_user_id}>. Ensure your profile is public.")

        return {game["appid"]: SteamGameInfo(game) for game in games}


def update_database_games_with_steam_user_data(db_session: Session, server_id: int, user_id: int, steam_games: dict[int, SteamGameInfo]) -> None:
    games = (
        db_session.query(Game)
            .filter(Game.server_id == server_id)
            .all()
    )  # type: list[Game]

    for game in games:
        update_database_game_user_data(db_session, server_id, game.id, user_id, game.steam_id, steam_games)


def update_database_game_user_data(db_session: Session, server_id: int, game_id: int, user_id: int, game_steam_id: int, owned_steam_games: dict[int, SteamGameInfo]) -> None:
    # Skip it if we don't know this game's Steam ID
    if game_steam_id is None:
        return

    # Get or create this user's game data
    game_user_data = db_session.get(GameUserData, (server_id, game_id, user_id))  # type: GameUserData
    if game_user_data is None:
        game_user_data = GameUserData(server_id=server_id, game_id=game_id, user_id=user_id)
        db_session.add(game_user_data)

    if game_user_data.owned is None:
        game_user_data.owned = game_steam_id in owned_steam_games

    if game_user_data.played_before is None:
        if game_steam_id not in owned_steam_games:
            game_user_data.played_before = False
        else:
            game_user_data.played_before = owned_steam_games[game_steam_id].playtime >= PLAYED_BEFORE_MINUTES_THRESHOLD
