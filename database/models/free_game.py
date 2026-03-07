import datetime
import enum

from sqlalchemy import Column, String, DateTime, Enum

from database.db import BaseModel


class GameType(enum.Enum):
    GAME = "game"
    DLC = "dlc"
    PACKAGE = "package"


class FreeGame(BaseModel):
    __tablename__ = "free_games"

    deal_id = Column(String, primary_key=True)
    game_name = Column(String, nullable=False)
    shop_name = Column(String, nullable=False)
    expiry_datetime = Column(DateTime(timezone=True), nullable=False)   # type: datetime.datetime
    url = Column(String, nullable=False)
    type = Column(Enum(GameType), nullable=False)   # type: GameType

    def to_markdown(self):
        """
        Formats the free game into a message announcing it, including a hyperlink.

        :return: a string describing that this game is free, for how long, and where to get it.
        """
        # Calculate how much time is left for this deal and add it to a presentable string
        expiry_string = ""
        timestamp = int(self.expiry_datetime.timestamp())
        formatted_time = f"<t:{timestamp}:f>"
        expiry_string += formatted_time
        time_until_expiry = self.expiry_datetime - datetime.datetime.now(self.expiry_datetime.tzinfo)
        days_until_expiry = time_until_expiry.days
        expiry_string += " ("
        if days_until_expiry > 0:
            expiry_string += f"{days_until_expiry} day"
            if days_until_expiry != 1:
                expiry_string += "s"
            expiry_string += " and "
        hours_until_expiry = int(time_until_expiry.seconds / 3600)
        expiry_string += f"{hours_until_expiry} hour"
        if hours_until_expiry != 1:
            expiry_string += "s"
        expiry_string += " left)"

        # Set up the the message
        message_text = f"**{self.game_name}**"
        if self.type != GameType.GAME:
            message_text += f" (*{self.type.value.upper()}*)"
        message_text += f" is free to keep on [{self.shop_name}](<{self.url}>) until {expiry_string}."
        return message_text
