from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from storage.db import BaseModel
from storage.user import User


class ServerMember(BaseModel):
    __tablename__ = "server_members"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    server_id = Column(Integer, ForeignKey("servers.id"), primary_key=True)
    alias = Column(String)

    user = relationship("User")     # type: User
