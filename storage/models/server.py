from sqlalchemy import Column, Integer

from storage.db import BaseModel


class Server(BaseModel):
    __tablename__ = "servers"

    id = Column(Integer, primary_key=True)
