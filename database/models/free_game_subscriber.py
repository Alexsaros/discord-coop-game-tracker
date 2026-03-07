from sqlalchemy import Column, Integer, ForeignKey

from database.db import BaseModel


class FreeGameSubscriber(BaseModel):
    __tablename__ = "free_game_subscribers"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
