from typing import Optional

import discord
from discord.ext.commands import Bot

from apis.discord import get_discord_guild_object
from database.db import db_session_scope
from database.models import LiveMessageType, LiveMessage, Server
from embeds.hall_of_game import generate_hog_embed
from embeds.list import generate_list_embeds
from embeds.utils import get_current_page_from_message_title
from shared.error_reporter import send_error_message
from shared.logger import log
from embeds.page_buttons_view import PageButtonsView


async def get_live_message_object(bot: Bot, server_id: int, message_type: LiveMessageType) -> Optional[discord.Message]:
    """
    Gets the message object for one of the live updating messages.
    Returns None if not found.
    """
    # Get the Discord guild object
    guild_object = await get_discord_guild_object(bot, server_id)
    if guild_object is None:
        return None

    with db_session_scope() as db_session:
        live_message = (
            db_session.query(LiveMessage)
                .filter(LiveMessage.server_id == server_id)
                .filter(LiveMessage.message_type == message_type)
                .first()
        )   # type: LiveMessage
        if live_message is None:
            # This server does not have the specified message
            return None

        # Get the Discord channel object
        channel_object = await guild_object.fetch_channel(live_message.channel_id)
        if channel_object is None:
            log(f"Discord could not find channel with ID {live_message.channel_id}. It has likely been deleted. Removing child message from the dataset...")
            db_session.delete(live_message)
            return None

        # Get the Discord message object
        try:
            return await channel_object.fetch_message(live_message.message_id)
        except discord.errors.NotFound:
            log(f"Could not find {message_type} with ID {live_message.message_id}. It has likely been deleted. Removing it from the dataset...")
            db_session.delete(live_message)
            return None


async def update_list(bot: Bot, server_id: int, page_number: int = None) -> None:
    list_message = await get_live_message_object(bot, server_id, LiveMessageType.LIST)
    if list_message is None:
        return

    list_embeds = (await generate_list_embeds(bot, server_id))
    if page_number is None:
        current_page = get_current_page_from_message_title(list_message.embeds[0].title)
        page_number = min(current_page, len(list_embeds))
    updated_list_embed = list_embeds[page_number - 1]

    page_buttons_view = PageButtonsView(bot, updated_list_embed.title, list_message.id, update_list, server_id)
    try:
        if updated_list_embed is not None:
            await list_message.edit(embed=updated_list_embed, view=page_buttons_view)
    except Exception as e:
        await send_error_message(bot, e)


async def update_hall_of_game(bot: Bot, server_id: int) -> None:
    hog_message = await get_live_message_object(bot, server_id, LiveMessageType.HALL_OF_GAME)
    if hog_message is None:
        return

    updated_hog_embed = await generate_hog_embed(bot, server_id)
    try:
        if updated_hog_embed is not None:
            await hog_message.edit(embed=updated_hog_embed)
    except Exception as e:
        await send_error_message(bot, e)


async def update_live_messages(bot: Bot, server_id: int, skip_hog=False) -> None:
    await update_list(bot, server_id)
    if not skip_hog:
        await update_hall_of_game(bot, server_id)


async def update_all_lists(bot: Bot) -> None:
    with db_session_scope() as db_session:
        servers = db_session.query(Server).all()    # type: list[Server]

        for server in servers:
            await update_list(bot, server.id)


async def load_list_views(bot: Bot):
    with db_session_scope() as db_session:
        list_messages = (
            db_session.query(LiveMessage)
                .filter(LiveMessage.message_type == LiveMessageType.LIST)
                .all()
        )   # type: list[LiveMessage]

    for list_message in list_messages:
        list_message_obj = await get_live_message_object(bot, list_message.server_id, LiveMessageType.LIST)
        if list_message_obj is not None:
            bot.add_view(PageButtonsView(bot, list_message_obj.embeds[0].title, list_message_obj.id, update_list, list_message.server_id))
