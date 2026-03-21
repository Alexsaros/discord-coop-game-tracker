import discord

from database.db import db_session_scope
from database.models import GameUserData, Game
from database.utils import get_server_members
from embeds.utils import generate_price_text
from shared.embed_pagination import paginate_embed_description

LIST_OWNED_GAMES_EMBED_COLOR = discord.Color.orange()


def generate_owned_games_embed(server_id: int) -> discord.Embed:
    with db_session_scope() as db_session:
        members = get_server_members(server_id)
        member_count = len(members)

        games = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.finished.is_(False))
                .all()
        )   # type: list[Game]

        owned_games = []    # type: list[Game]
        for game in games:
            game_user_data_list = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == game.server_id)
                    .filter(GameUserData.game_id == game.id)
                    .all()
            )   # type: list[GameUserData]

            owned_count = sum(1 for data in game_user_data_list if data.owned is True)
            if owned_count >= member_count:
                owned_games.append(game)

        games_list = []
        for game in owned_games:
            game_text = f"{game.id} -"
            if game.steam_id is not None:
                game_link = f"https://store.steampowered.com/app/{game.steam_id}"
                game_text += f" [{game.name}]({game_link})"
            else:
                game_text += " " + game.name
            price_text = generate_price_text(game)
            if price_text:
                game_text += " " + generate_price_text(game)

            games_list.append(game_text)

        title_text = f"Games owned by everyone"
        games_list_text = "\n".join(games_list)

        list_embed = discord.Embed(
            title=title_text,
            description=games_list_text,
            color=LIST_OWNED_GAMES_EMBED_COLOR
        )
        embeds = paginate_embed_description(list_embed)
        list_embed = embeds[0]
        return list_embed
