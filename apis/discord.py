import discord
from discord.ext.commands import Bot


async def get_discord_user(bot: Bot, user_id: int) -> discord.User:
    user = bot.get_user(user_id)
    if user is None:
        user = await bot.fetch_user(user_id)
    return user
