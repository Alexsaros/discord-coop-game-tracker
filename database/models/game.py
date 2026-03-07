import enum

from sqlalchemy import Column, Integer, String, Boolean, JSON, Float, Enum, ForeignKey
from sqlalchemy.ext.mutable import MutableList

from database.db import BaseModel


class ReleaseState(enum.Enum):
    RELEASED = "released"
    EARLY_ACCESS = "early access"
    UNRELEASED = "unreleased"


class Game(BaseModel):
    __tablename__ = "games"

    server_id = Column(Integer, ForeignKey("servers.id"), primary_key=True)
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    submitter = Column(String, nullable=False)

    tags = Column(MutableList.as_mutable(JSON), default=list)

    player_count = Column(Integer)
    steam_id = Column(Integer)
    price_current = Column(Float)
    price_original = Column(Float)
    local = Column(Boolean, default=False)
    release_state = Column(Enum(ReleaseState))

    finished = Column(Boolean, default=False)
    finished_timestamp = Column(Float)
