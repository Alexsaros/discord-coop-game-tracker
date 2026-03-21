from typing import Optional

import discord
from discord.ext.commands import Bot

from apis.discord import get_discord_guild_object
from database.db import db_session_scope
from database.models import Game, GameUserData
from database.utils import get_server_members
from embeds.utils import get_users_aliases_string, generate_price_text, sort_games_by_score
from shared.embed_pagination import paginate_embed_description

LIST_EMBED_COLOR = discord.Color.blurple()


async def generate_list_embeds(bot: Bot, server_id: int) -> Optional[list[discord.Embed]]:
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
