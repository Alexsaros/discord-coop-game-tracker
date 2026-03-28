from sqlalchemy.orm import Session

from database.db import db_session_scope
from database.models import ServerMember, Game, User
from shared.exceptions import GameNotFoundException, UserNotFoundException


def get_server_members(server_id: int) -> list[ServerMember]:
    with db_session_scope() as db_session:
        members = (
            db_session.query(ServerMember)
                .filter(ServerMember.server_id == server_id)
                .all()
        )  # type: list[ServerMember]

    return members


def get_game(db_session: Session, server_id: int, game_name: str, finished=False) -> Game:
    """
    Returns the game's data from the database as a Game object.
    Raises a GameNotFoundException if the game was not found.
    """
    try:
        # Check if the game was passed as ID
        game_id = str(int(game_name))
        game = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.id == game_id)
                .filter(Game.finished.is_(finished))
                .first()
        )   # type: Game

        if game is None:
            # TODO find an easier way to handle these exception messages
            if finished:
                raise GameNotFoundException(f"Could not find finished game with ID \"{game_id}\". Use: !finish \"game name\", to mark a game as finished.")
            else:
                raise GameNotFoundException(f"Could not find game with ID \"{game_id}\". Use: !add \"game name\", to add a new game.")

        return game

    except ValueError:
        # A name was given to find the game
        game = (
            db_session.query(Game)
                .filter(Game.server_id == server_id)
                .filter(Game.name.ilike(game_name))
                .filter(Game.finished.is_(finished))
                .first()
        )   # type: Game

        if game is None:
            if finished:
                raise GameNotFoundException(f"Could not find finished game with name \"{game_name}\". Use: !finish \"game name\", to mark a game as finished.")
            else:
                raise GameNotFoundException(f"Could not find game with name \"{game_name}\". Use: !add \"game name\", to add a new game.")

        return game


def get_user_by_name(username: str) -> User:
    with db_session_scope() as db_session:
        user = (
            db_session.query(User)
                .filter(User.username == username)
                .first()
        )  # type: User

        if user is None:
            user = (
                db_session.query(User)
                    .filter(User.global_name == username)
                    .first()
            )  # type: User

    if user is None:
        raise UserNotFoundException(f"Could not find user with username \"{username}\".")

    return user

