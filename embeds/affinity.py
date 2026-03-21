from collections import defaultdict

import discord

from database.db import db_session_scope
from database.models import GameUserData, User

AFFINITY_EMBED_COLOR = discord.Color.purple()


def generate_affinity_embed(server_id: int, user_id: int) -> discord.Embed:
    with db_session_scope() as db_session:
        game_user_data_votes = (
            db_session.query(GameUserData)
                .filter(GameUserData.server_id == server_id)
                .filter(GameUserData.vote.isnot(None))
                .all()
        )   # type: list[GameUserData]

        vote_data_by_game = defaultdict(list)   # type: dict[int, list[GameUserData]]
        for data in game_user_data_votes:
            vote_data_by_game[data.game_id].append(data)

        similarity_scores = defaultdict(lambda: defaultdict(int))   # type: dict[int, dict[str, int]]
        for game_id, game_vote_data in vote_data_by_game.items():
            # Skip this game if the user hasn't voted on it
            user_data = next((data for data in game_vote_data if data.user_id == user_id), None)
            if user_data is None:
                continue

            # Check the votes for this game
            for data in game_vote_data:
                if data.user_id == user_id:
                    continue

                similarity_scores[data.user_id]["error_sum"] += abs(user_data.vote - data)
                similarity_scores[data.user_id]["votes"] += 1

        similarity_percentages = []
        for user, stats in similarity_scores.items():
            if stats["count"] > 0:
                # Calculate the Mean Absolute Error
                mae = stats["error_sum"] / stats["count"]
                # Convert it to a percentage
                similarity = (1 - (mae / 10)) * 100
                similarity_percentages.append((user, round(similarity, 2)))

        # Sort it so the highest affinity shows up first
        similarity_percentages = sorted(similarity_percentages, key=lambda x: x[1], reverse=True)

        if len(similarity_percentages) == 0:
            affinity_text = "No people have voted on the same games."
        else:
            entries = []
            for user, affinity in similarity_percentages:
                entries.append(f"{user}: {affinity}%")
            affinity_text = "\n".join(entries)

        user_db_entry = db_session.get(User, user_id)   # type: User

        # Get info on the game and display it in an embed
        title = f"{user_db_entry.global_name}'s affinity with others"
        affinity_embed = discord.Embed(
            title=title,
            description=affinity_text,
            color=AFFINITY_EMBED_COLOR
        )
        return affinity_embed
