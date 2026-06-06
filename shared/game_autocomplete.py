from typing import Optional

from discord import app_commands
from discord.interactions import Interaction

from database.db import db_session_scope
from database.models import Game


# Caches the list of games for each  server ID
_game_cache: dict[int, list[Game]] = {}


def clear_game_cache(server_id: int):
    _game_cache.pop(server_id, None)


def autocomplete_game(finished: Optional[bool] = None):

    async def autocomplete(interaction: Interaction, typed_text: str) -> list[app_commands.Choice[str]]:
        server_id = interaction.guild.id
        typed_text = typed_text.lower()

        # Get the games cached for this server
        games = _game_cache.get(server_id)

        if games is None:
            # Get and cache the games for this server
            with db_session_scope() as db_session:
                games = (
                    db_session.query(Game)
                        .filter(Game.server_id == server_id)
                        .all()
                )  # type: list[Game]

            _game_cache[server_id] = games

        # Check if we need to filter (un)finished games
        if finished is not None:
            games = [game for game in games if game.finished is finished]

        suggestions = []
        for game in games:
            suggestion_text = f"{game.id} - {game.name}"
            # Filter games based on what the user typed
            if typed_text in suggestion_text.lower():
                suggestion = app_commands.Choice(
                    name=suggestion_text,
                    value=str(game.id)
                )
                suggestions.append(suggestion)

        # Discord allows max 25 suggestions
        return suggestions[:25]

    return autocomplete
