import discord
from discord.ext.commands import Bot
from discord.ui import View, Button, Select
from sqlalchemy.orm import Session

from database.db import db_session_scope
from database.models import Game, GameUserData
from embeds.utils import get_game_embed_field
from shared.error_reporter import send_error_message
from shared.live_messages import update_live_messages

EDIT_GAME_EMBED_COLOR = discord.Color.dark_blue()


class EditGame:

    def __init__(self, bot: Bot, server_id: int, game_id: int, channel_id: int):
        self.bot = bot
        self.server_id = server_id
        self.game_id = game_id
        self.channel_id = channel_id
        self.message_object = None

    async def send_message(self):
        channel_object = await self.bot.fetch_channel(self.channel_id)

        game_embed = self.get_embed()
        game_view = self.EditGameView(self.bot, self)
        self.message_object = await channel_object.send(embed=game_embed, view=game_view)    # type: discord.Message

    async def update_message(self):
        game_embed = self.get_embed()
        game_view = self.EditGameView(self.bot, self)
        await self.message_object.edit(embed=game_embed, view=game_view)    # type: discord.Message

        await update_live_messages(self.bot, self.server_id, skip_hog=True)

    def get_game(self, db_session: Session) -> Game:
        return (
            db_session.query(Game)
                .filter(Game.server_id == self.server_id)
                .filter(Game.id == self.game_id)
                .filter(Game.finished.is_(False))
                .first()
        )  # type: Game

    def get_embed(self):
        with db_session_scope() as db_session:
            game = self.get_game(db_session)

            # Get info on the game and display it in an embed
            embed_field_info = get_game_embed_field(game)
            title = embed_field_info["name"]
            embed_field_info["name"] = ""
            game_embed = discord.Embed(title=title, color=EDIT_GAME_EMBED_COLOR)
            game_embed.add_field(**embed_field_info)
            return game_embed

    async def delete_message(self):
        await self.message_object.delete()

    class EditGameView(View):

        def __init__(self, bot: Bot, edit_game_object):
            super().__init__(timeout=None)
            self.bot = bot
            self.edit_game_object = edit_game_object    # type: EditGame

            self.add_item(self.edit_game_object.VoteMenu(self.bot, self.edit_game_object))
            self.add_item(Button(style=discord.ButtonStyle.blurple, label="Toggle owned", custom_id="owned"))
            self.add_item(Button(style=discord.ButtonStyle.blurple, label="Toggle played before", custom_id="played_before"))
            self.add_item(Button(style=discord.ButtonStyle.grey, label="Toggle single copy required", custom_id="local"))
            self.add_item(self.edit_game_object.PlayersMenu(self.bot, self.edit_game_object))
            self.add_item(Button(style=discord.ButtonStyle.red, label="Close", custom_id="close"))

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            try:
                with db_session_scope() as db_session:
                    await interaction.response.defer()

                    user_id = interaction.user.id
                    button_id = interaction.data.get("custom_id")
                    game = self.edit_game_object.get_game(db_session)
                    game_user_data = db_session.get(GameUserData, (game.server_id, game.id, user_id))  # type: GameUserData
                    if game_user_data is None:
                        game_user_data = GameUserData(server_id=game.server_id, game_id=game.id, user_id=user_id)
                        db_session.add(game_user_data)

                    if button_id == "owned":
                        owned = game_user_data.owned if game_user_data.owned is not None else False
                        game_user_data.owned = not owned
                    elif button_id == "played_before":
                        played_before = game_user_data.played_before if game_user_data.played_before is not None else False
                        game_user_data.played_before = not played_before
                    elif button_id == "local":
                        game.local = not game.local
                    elif button_id == "close":
                        await self.edit_game_object.delete_message()
                        return True
                    else:
                        return True

                await self.edit_game_object.update_message()

            except Exception as e:
                await send_error_message(self.bot, e)

            return True

    class VoteMenu(Select):
        def __init__(self, bot: Bot, edit_game_object):
            self.bot = bot
            self.edit_game_object = edit_game_object    # type: EditGame
            # The options range from 10 to 0
            options = [discord.SelectOption(label=str(i), value=str(i)) for i in range(10, -1, -1)]
            super().__init__(placeholder="Vote", options=options)

        async def callback(self, interaction: discord.Interaction):

            try:
                with db_session_scope() as db_session:
                    score = int(self.values[0])
                    user_id = interaction.user.id
                    game = self.edit_game_object.get_game(db_session)

                    game_user_data = db_session.get(GameUserData, (game.server_id, game.id, user_id))   # type: GameUserData
                    if game_user_data is None:
                        game_user_data = GameUserData(server_id=game.server_id, game_id=game.id, user_id=user_id)
                        db_session.add(game_user_data)

                    game_user_data.vote = score

                await self.edit_game_object.update_message()

            except Exception as e:
                await send_error_message(self.bot, e)

    class PlayersMenu(Select):
        def __init__(self, bot: Bot, edit_game_object):
            self.bot = bot
            self.edit_game_object = edit_game_object    # type: EditGame
            # The options range from 1 to 4
            options = [discord.SelectOption(label=str(i), value=str(i)) for i in range(1, 5)]
            super().__init__(placeholder="Player count", options=options)

        async def callback(self, interaction: discord.Interaction):
            try:
                with db_session_scope() as db_session:
                    player_count = int(self.values[0])
                    game = self.edit_game_object.get_game(db_session)
                    game.player_count = player_count

                await self.edit_game_object.update_message()

            except Exception as e:
                await send_error_message(self.bot, e)
