from sqlalchemy import Column, Integer, ForeignKey, Float

from storage.db import BaseModel


class Vote(BaseModel):
    __tablename__ = "votes"

    server_id = Column(Integer, ForeignKey("servers.id"), primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)

    score = Column(Float, nullable=False)
