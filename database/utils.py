from database.db import db_session_scope
from database.models import ServerMember


def get_server_members(server_id: int) -> list[ServerMember]:
    with db_session_scope() as db_session:
        members = (
            db_session.query(ServerMember)
                .filter(ServerMember.server_id == server_id)
                .all()
        )  # type: list[ServerMember]

    return members
