import discord
from discord.ext.commands import Bot
from discord.ui import Select
from sqlalchemy.orm import joinedload

from database.db import db_session_scope
from database.models import ServerMember, LiveMessage, LiveMessageType
from embeds.page_buttons_view import PageButtonsView
from shared.error_reporter import send_error_message


class ListView(PageButtonsView):

    def __init__(self, bot: Bot, embed_title: str, message_id: int, update_function: callable, server_id: int):
        super().__init__(bot=bot, embed_title=embed_title, message_id=message_id, update_function=update_function, server_id=server_id)

        self.add_item(self.UserSelection(bot=bot, list_view_object=self))

    class UserSelection(Select):
        def __init__(self, bot: Bot, list_view_object):
            self.bot = bot
            self.list_view_object = list_view_object    # type: ListView

            with db_session_scope() as db_session:
                members = (
                    db_session.query(ServerMember)
                        .options(joinedload(ServerMember.user))  # Also preemptively retrieve User data
                        .filter(ServerMember.server_id == self.list_view_object.server_id)
                        .all()
                )  # type: list[ServerMember]

            options = []
            for member in members:
                user_text = member.user.global_name
                if member.alias:
                    user_text += f" ({member.alias})"
                options.append(discord.SelectOption(label=user_text, value=member.user_id))

            super().__init__(placeholder="Toggle user to play with", options=options, custom_id=f"{self.list_view_object.message_id}_userSelection")

        async def callback(self, interaction: discord.Interaction):
            try:
                selected_user_id = int(self.values[0])

                with db_session_scope() as db_session:
                    live_message = (
                        db_session.query(LiveMessage)
                            .filter(LiveMessage.server_id == self.list_view_object.server_id)
                            .filter(LiveMessage.message_type == LiveMessageType.LIST)
                            .first()
                    )  # type: LiveMessage
                    if live_message is None:
                        await send_error_message(self.bot, f"Selected a user to play with for server {self.list_view_object.server_id}, but the server does not have a list object.")
                        return True

                    if selected_user_id in live_message.selected_user_ids:
                        live_message.selected_user_ids.remove(selected_user_id)
                    else:
                        live_message.selected_user_ids.append(selected_user_id)

                await self.list_view_object.update_function(self.bot, self.list_view_object.server_id, None)

            except Exception as e:
                await send_error_message(self.bot, e)
