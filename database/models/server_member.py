from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from database.db import BaseModel
from database.models.user import User


class ServerMember(BaseModel):
    __tablename__ = "server_members"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    server_id = Column(Integer, ForeignKey("servers.id"), primary_key=True)
    alias = Column(String)
    steam_id = Column(Integer)

    user = relationship("User")     # type: User
