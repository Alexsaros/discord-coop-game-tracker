import traceback

from discord.ext.commands import Bot

from apis.discord import get_discord_user
from constants import MESSAGE_MAX_CHARACTERS, DEVELOPER_USER_ID


def log(message):
    message = str(message)
    print(message)
    with open("log.log", "a", encoding="utf-8") as f:
        f.write(message + "\n")


async def send_error_message(bot: Bot, exception):
    if isinstance(exception, Exception):
        message = ''.join(traceback.format_exception(exception))
    else:
        message = str(exception)
    log(message)

    developer = await get_discord_user(bot, DEVELOPER_USER_ID)
    for i in range(0, len(message), MESSAGE_MAX_CHARACTERS - 6):
        message_slice = message[i:i + MESSAGE_MAX_CHARACTERS - 6]
        await developer.send(f"```{message_slice}```")
