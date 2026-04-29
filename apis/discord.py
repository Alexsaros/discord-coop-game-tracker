from typing import Optional

import discord
from discord.ext.commands import Bot

from shared.exceptions import GuildNotFoundException
from shared.logger import log


async def get_discord_user(bot: Bot, user_id: int) -> discord.User:
    user = bot.get_user(user_id)
    if user is None:
        user = await bot.fetch_user(user_id)
    return user


async def get_discord_guild_object(bot: Bot, server_id: int) -> discord.Guild:
    """
    Gets Discord's guild object for the given server ID.
    Returns None if not found.
    """
    # Get the Discord server object
    guild_object = bot.get_guild(server_id)
    if guild_object is None:
        guild_object = await bot.fetch_guild(server_id)
        if guild_object is None:
            raise GuildNotFoundException(f"Discord could not find guild with ID {server_id}.")
    return guild_object


async def get_user_voice_channel(bot: Bot, user_id: int, server_id: int) -> Optional[discord.VoiceChannel]:
    """
    Returns the voice channel the user is in, or None if they're not in a voice channel or could not be found.
    """
    guild = await get_discord_guild_object(bot, server_id)

    user = guild.get_member(user_id)    # type: discord.Member
    if user is None:
        log(f"No user with ID {user_id} found.")
        return None

    if user.voice is None or user.voice.channel is None:
        log(f"User with ID {user_id} is not in a voice channel.")
        return None

    return user.voice.channel


async def delete_message(message: discord.Message) -> None:
    try:
        await message.delete()
    except discord.Forbidden:
        # Message is likely a DM
        pass
