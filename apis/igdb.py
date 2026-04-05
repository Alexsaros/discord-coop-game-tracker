import os
from typing import Optional

import aiohttp
from discord.ext.commands import Bot

from dotenv import load_dotenv

from shared.error_reporter import send_error_message
from shared.exceptions import ApiException

load_dotenv()

# Set IGDB/Twitch credentials via environment variables
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

TWITCH_TOKEN_ENDPOINT = "https://id.twitch.tv/oauth2/token"
IGDB_GAMES_ENDPOINT = "https://api.igdb.com/v4/games"
IGDB_MULTIPLAYER_MODES_ENDPOINT = "https://api.igdb.com/v4/multiplayer_modes"


class MultiplayerInfo:

    def __init__(self) -> None:
        super().__init__()
        self.campaign_coop = None
        self.max_players_offline = 0
        self.max_players_online = 0

    def update_data(self, multiplayer_data: dict):
        campaign_coop = multiplayer_data.get("campaigncoop", None)
        # Do not allow the attribute to be set to False if it had been set to True
        if campaign_coop is not None and self.campaign_coop is not True:
            self.campaign_coop = campaign_coop

        max_players_offline = 1 if multiplayer_data.get("offlinecoop", None) else 0
        self.max_players_offline = max(max_players_offline, self.max_players_offline)

        max_players_offline = multiplayer_data.get("offlinecoopmax", 0)
        self.max_players_offline = max(max_players_offline, self.max_players_offline)

        max_players_offline = multiplayer_data.get("offlinemax", 0)
        self.max_players_offline = max(max_players_offline, self.max_players_offline)

        max_players_online = multiplayer_data.get("onlinecoopmax", 0)
        self.max_players_online = max(max_players_online, self.max_players_online)

        max_players_online = multiplayer_data.get("onlinemax", 0)
        self.max_players_online = max(max_players_online, self.max_players_online)


class IgdbApi:

    def __init__(self, session: aiohttp.ClientSession) -> None:
        super().__init__()
        self.headers = {}
        self.session = session

    async def authenticate(self):
        params = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials",
        }

        response = await self.session.post(TWITCH_TOKEN_ENDPOINT, params=params)
        try:
            response.raise_for_status()
        except Exception as e:
            raise ApiException(f"Failed to get Twitch access token. {e}", e)

        payload = await response.json()
        access_token = payload.get("access_token")

        self.headers = {
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {access_token}",
        }

    async def get_game(self, game_name: str) -> dict:
        body = f'search "{game_name}"; fields name, multiplayer_modes; limit 10;'
        response = await self.session.post(IGDB_GAMES_ENDPOINT, headers=self.headers, data=body)
        try:
            response.raise_for_status()
        except Exception as e:
            raise ApiException(f"Failed to get game from IGDB. {e}", e)

        games = await response.json()
        if len(games) == 0:
            return {}

        # Take the first returned game unless we have an exact match
        requested_game = games[0]
        for game in games:
            if game["name"].lower() == game_name.lower():
                requested_game = game
                break

        return requested_game

    async def get_multiplayer_info(self, multiplayer_modes: list[int]) -> MultiplayerInfo:
        body = f'fields campaigncoop, offlinecoop, offlinecoopmax, offlinemax, onlinecoopmax, onlinemax; where id = ({",".join(map(str, multiplayer_modes))});'
        response = await self.session.post(IGDB_MULTIPLAYER_MODES_ENDPOINT, headers=self.headers, data=body)
        try:
            response.raise_for_status()
        except Exception as e:
            raise ApiException(f"Failed to get multiplayer modes from IGDB. {e}", e)

        modes = await response.json()   # type: list[dict]

        multiplayer_info = MultiplayerInfo()
        for mode in modes:
            multiplayer_info.update_data(mode)

        return multiplayer_info


async def get_multiplayer_info_from_igdb(bot: Bot, game_name: str) -> Optional[MultiplayerInfo]:
    async with aiohttp.ClientSession() as session:
        api = IgdbApi(session)
        try:
            await api.authenticate()

            game = await api.get_game(game_name)
            if "multiplayer_modes" in game:
                return await api.get_multiplayer_info(game["multiplayer_modes"])
            elif len(game) != 0:
                multiplayer_info = MultiplayerInfo()
                multiplayer_info.max_players_offline = 1
                return multiplayer_info

        except ApiException as e:
            await send_error_message(bot, f"Failed to get free-to-keep games. {e}")

        return None
