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


def generate_unvoted_embed(server_id: int) -> Optional[discord.Embed]:
    with db_session_scope() as db_session:
        games = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.finished.is_(False))
                .all()
        )  # type: list[Game]

        members = get_server_members(server_id)
        member_ids = [member.user_id for member in members]

        unvoted_games_map = {}  # type: dict[int, list[Game]]
        for game in games:
            game_user_data_votes = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == server_id)
                    .filter(GameUserData.game_id == game.id)
                    .filter(GameUserData.vote.isnot(None))
                    .all()
            )  # type: list[GameUserData]

            voter_ids = [game_user_data.user_id for game_user_data in game_user_data_votes]
            non_voters = list(set(member_ids) - set(voter_ids))
            non_voters.sort()

            for non_voter in non_voters:
                if non_voter not in unvoted_games_map:
                    unvoted_games_map[non_voter] = []
                unvoted_games_map[non_voter].append(game)

    if len(unvoted_games_map) == 0:
        return None

    unvoted_counts = []
    for user_id, unvoted_games in unvoted_games_map.items():
        alias = get_users_aliases_string(server_id, [user_id])
        unvoted_counts.append(f"{alias}: {len(unvoted_games)}")

    description = ", ".join(unvoted_counts)
    return discord.Embed(
        title="Amount of games not yet voted on",
        description=description,
        color=LIST_EMBED_COLOR
    )


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

            # Add an asterisk if this game contains notes
            if len(game.notes) > 0:
                game_text += "\\*"

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
