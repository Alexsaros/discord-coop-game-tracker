import discord
from discord.ext.commands import Bot

from apis.discord import get_discord_guild_object
from constants import EMBED_MAX_CHARACTERS
from database.db import db_session_scope
from database.models import Game
from database.utils import get_server_members
from embeds.utils import sort_games_by_score
from shared.logger import log

HOG_EMBED_COLOR = discord.Color.blurple()


async def generate_hog_embed(bot: Bot, server_id: int):
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
            color=HOG_EMBED_COLOR
        )
        return list_embed
