import discord

from database.db import db_session_scope
from database.models import User, Game, GameUserData
from database.utils import get_server_members
from embeds.utils import generate_price_text, get_users_aliases_string
from shared.embed_pagination import paginate_embed_description

LIST_PLAY_WITHOUT_EMBED_COLOR = discord.Color.red()


def generate_play_without_embed(server_id: int, user: User) -> discord.Embed:
    with db_session_scope() as db_session:
        members = get_server_members(server_id)
        member_count = len(members)
        game_scores = []    # type: list[tuple[Game, int]]

        games = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.finished.is_(False))
                .all()
        )   # type: list[Game]

        for game in games:
            game_user_data_votes = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == server_id)
                    .filter(GameUserData.game_id == game.id)
                    .filter(GameUserData.vote.isnot(None))
                    .all()
            )  # type: list[GameUserData]

            # Skip games that the user voted 5 or higher on
            vote_user = next((data.vote for data in game_user_data_votes if data.user_id == user.id), 5)
            if vote_user >= 5:
                continue

            # Count the score for this game
            total_score = 0
            for data in game_user_data_votes:
                if data.user_id != user.id:
                    total_score += data.vote
                else:
                    total_score -= data.vote * member_count
            # Use a score of 5 for the non-voters
            non_voters_ids = member_count - len(game_user_data_votes)
            total_score += non_voters_ids * 5

            game_scores.append((game, total_score))

        sorted_games = sorted(game_scores, key=lambda x: x[1], reverse=True)

        games_list = []     # type: list[str]
        for game, score in sorted_games:
            game_user_data_votes = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == server_id)
                    .filter(GameUserData.game_id == game.id)
                    .filter(GameUserData.vote.isnot(None))
                    .all()
            )  # type: list[GameUserData]

            # Get everyone who hasn't voted yet
            non_voters_ids = [member.id for member in members]
            for data in game_user_data_votes:
                if data.user_id in non_voters_ids:
                    non_voters_ids.remove(data.user_id)
            non_voters_text = get_users_aliases_string(server_id, non_voters_ids)

            game_text = f"{game.id} -"
            if game.steam_id is not None:
                game_link = "https://store.steampowered.com/app/" + str(game.steam_id)
                game_text += f" [{game.name}]({game_link})"
            else:
                game_text += " " + game.name
            price_text = generate_price_text(game)
            if price_text:
                game_text += " " + generate_price_text(game)
            if non_voters_text:
                game_text += " " + non_voters_text

            games_list.append(game_text)

        title_text = f"Potential games to play without {user.global_name}"
        games_list_text = "\n".join(games_list)

        list_embed = discord.Embed(
            title=title_text,
            description=games_list_text,
            color=LIST_PLAY_WITHOUT_EMBED_COLOR
        )
        embeds = paginate_embed_description(list_embed)
        list_embed = embeds[0]
        return list_embed
