from sqlalchemy import Column, Integer, ForeignKey, Float, Boolean

from database.db import BaseModel


class GameUserData(BaseModel):
    __tablename__ = "game_user_data"

    server_id = Column(Integer, ForeignKey("servers.id"), primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)

    vote = Column(Float)
    owned = Column(Boolean)
    played_before = Column(Boolean)

    enjoyment_score = Column(Float)
