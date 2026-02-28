import enum

from sqlalchemy import Column, String, Enum, Integer, ForeignKey

from storage.db import BaseModel


class LiveMessageType(enum.Enum):
    LIST = "list"
    HALL_OF_GAME = "hall of game"


class LiveMessage(BaseModel):
    __tablename__ = "live_messages"

    server_id = Column(Integer, ForeignKey("servers.id"), index=True)   # Is empty for DMs
    channel_id = Column(String, nullable=False)
    message_id = Column(String, primary_key=True, nullable=False)
    message_type = Column(Enum(LiveMessageType), nullable=False, index=True)
