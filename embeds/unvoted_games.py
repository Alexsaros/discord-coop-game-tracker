import discord
from discord.ext.commands import Bot
from discord.ui import View, Button
from sqlalchemy.orm import Session

from apis.discord import get_discord_user, get_discord_guild_object
from database.db import db_session_scope
from database.models import Game, GameUserData
from embeds.edit_game import EditGame
from shared.error_reporter import send_error_message


class UnvotedGames:

    def __init__(self, bot: Bot, server: discord.Guild, user: discord.User):
        self.bot = bot
        self.server_id = server.id
        self.server_name = server.name
        self.user = user
        self.user_id = user.id
        self.message_object = None

    async def send_message(self):
        unvoted_games_embed = self.get_embed()
        unvoted_games_view = self.UnvotedGamesView(self)
        self.message_object = await self.user.send(embed=unvoted_games_embed, view=unvoted_games_view)  # type: discord.Message

    def get_embed(self):
        return discord.Embed(
            title=f"Unvoted games",
            description=f"Press the buttons to see games that you haven't yet voted on in server: {self.server_name}",
            color=discord.Color.red()
        )

    async def delete_message(self):
        await self.message_object.delete()

    class UnvotedGamesView(View):

        def __init__(self, unvoted_games_object):
            super().__init__(timeout=None)
            self.bot = unvoted_games_object.bot
            self.unvoted_games_object = unvoted_games_object    # type: UnvotedGames

            self.add_item(Button(style=discord.ButtonStyle.blurple, label="Show next unvoted game", custom_id="next"))
            self.add_item(Button(style=discord.ButtonStyle.blurple, label="Show all unvoted games", custom_id="send_all"))
            self.add_item(Button(style=discord.ButtonStyle.red, label="Close", custom_id="close"))

        def get_unvoted_games(self, db_session: Session) -> list[Game]:
            games = (
                db_session.query(Game)
                    .filter(Game.server_id == self.unvoted_games_object.server_id)
                    .filter(Game.finished.is_(False))
                    .all()
            )  # type: list[Game]

            unvoted_games = []
            for game in games:
                game_user_data_vote = (
                    db_session.query(GameUserData)
                        .filter(GameUserData.server_id == self.unvoted_games_object.server_id)
                        .filter(GameUserData.user_id == self.unvoted_games_object.user_id)
                        .filter(GameUserData.game_id == game.id)
                        .filter(GameUserData.vote.isnot(None))
                        .first()
                )  # type: GameUserData

                if game_user_data_vote is None:
                    unvoted_games.append(game)

            return unvoted_games

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            try:
                await interaction.response.defer()

                button_id = interaction.data.get("custom_id")

                if button_id == "close":
                    await self.unvoted_games_object.delete_message()
                    return True

                with db_session_scope() as db_session:
                    unvoted_games = self.get_unvoted_games(db_session)
                    if len(unvoted_games) == 0:
                        await interaction.followup.send("No unvoted games at the moment.", ephemeral=True)
                        return True

                    dm_channel = self.unvoted_games_object.user.dm_channel
                    if dm_channel is None:
                        dm_channel = await self.unvoted_games_object.user.create_dm()

                    if button_id == "next":
                        game = unvoted_games[0]
                        edit_game = EditGame(self.bot, self.unvoted_games_object.server_id, game.id, dm_channel.id)
                        await edit_game.send_message()

                    elif button_id == "send_all":
                        for game in unvoted_games:
                            edit_game = EditGame(self.bot, self.unvoted_games_object.server_id, game.id, dm_channel.id)
                            await edit_game.send_message()

            except Exception as e:
                await send_error_message(self.bot, e)

            return True
