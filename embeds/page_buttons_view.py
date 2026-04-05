import discord
from discord.ext.commands import Bot
from discord.ui import View, Button

from embeds.utils import get_current_page_from_message_title, get_total_pages_from_message_title
from shared.error_reporter import send_error_message


class PageButtonsView(View):

    def __init__(self, bot: Bot, embed_title: str, message_id: int, update_function: callable, server_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.message_id = message_id
        self.update_function = update_function
        self.server_id = server_id

        self.current_page = get_current_page_from_message_title(embed_title)
        total_pages = get_total_pages_from_message_title(embed_title)
        disabled_previous = self.current_page <= 1
        disabled_next = self.current_page >= total_pages

        self.add_item(Button(style=discord.ButtonStyle.blurple, label="Previous page", custom_id=f"{self.message_id}_previousPage", disabled=disabled_previous))
        self.add_item(Button(style=discord.ButtonStyle.grey, label=f"Page {self.current_page}/{total_pages}", custom_id=f"{self.message_id}_pageNumber", disabled=True))
        self.add_item(Button(style=discord.ButtonStyle.blurple, label="Next page", custom_id=f"{self.message_id}_nextPage", disabled=disabled_next))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            # noinspection PyUnresolvedReferences
            await interaction.response.defer()

            action = interaction.data.get("custom_id").split("_")[-1]
            new_page = self.current_page
            if action == "previousPage":
                new_page -= 1
            elif action == "nextPage":
                new_page += 1

            await self.update_function(self.bot, self.server_id, new_page)
        except Exception as e:
            await send_error_message(self.bot, e)

        return True
