from sqlalchemy import Column, String

from storage.db import BaseModel


class FreeGame(BaseModel):
    __tablename__ = "free_games"

    # TODO improve this when known for certain where we get this info from
    deal_id = Column(String, primary_key=True)
    game_name = Column(String, nullable=False)
    shop_name = Column(String, nullable=False)
    expiry_datetime = Column(String, nullable=False)
    url = Column(String, nullable=False)
    type = Column(String, nullable=False)   # Can be "game", "dlc", or "package"
