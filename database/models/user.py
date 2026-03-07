from sqlalchemy import Column, Integer, String

from database.db import BaseModel


class User(BaseModel):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=False)
    global_name = Column(String, nullable=False)
