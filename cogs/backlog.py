import time

import discord
from discord.ext import commands
from discord.ext.commands import guild_only

from apis.discord import delete_message
from apis.igdb import get_multiplayer_info_from_igdb
from apis.steam import get_steam_game_banner, get_steam_game_price, update_game_steam_prices_fields, \
    search_steam_for_game, update_database_steam_prices
from apis.steam_web import update_database_game_user_data, get_owned_steam_games, get_steam_user_id, \
    update_database_games_with_steam_user_data
from database.db import db_session_scope
from database.models import ServerMember, LiveMessage, LiveMessageType, GameUserData, Game
from database.utils import get_game, get_server_members
from embeds.edit_game import EditGame
from embeds.hall_of_game import generate_hog_embed
from embeds.list import generate_unvoted_embed, generate_filter_embed, generate_list_embeds
from embeds.list_view import ListView
from embeds.owned_games import generate_owned_games_embed
from embeds.unvoted_games import UnvotedGames
from shared.exceptions import NoAccessException, GameNotFoundException
from shared.live_messages import update_live_messages, update_list, get_live_message_object, update_hall_of_game, \
    update_all_lists
from shared.logger import log


class Backlog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def update_steam_prices(self) -> None:
        await update_database_steam_prices()
        await update_all_lists(self.bot)

    @guild_only()
    @commands.command(name="update_prices", help="Retrieves the latest prices from Steam. Example: !update_prices.")
    async def update_prices(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")

        await update_database_steam_prices()
        await update_all_lists(self.bot)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="add", help="Adds a new game to the list. Example: !add \"game name\".")
    async def add_game(self, ctx, game_name):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        try:
            int(game_name)
            await ctx.send("Game name cannot be a number.")
            return
        except ValueError:
            pass

        with db_session_scope() as db_session:
            try:
                game = get_game(db_session, server_id, game_name, finished=True)
                log(f"Game already finished: {str(game.name)}")
                await ctx.send("This game has already been finished.")
                return
            except GameNotFoundException:
                pass

            try:
                game = get_game(db_session, server_id, game_name)
                log(f"Game already added: {str(game.name)}")
                await ctx.send("This game has already been added.")
                return
            except GameNotFoundException:
                last_game_id = (
                    db_session.query(Game.id)
                        .filter(Game.server_id == server_id)
                        .order_by(Game.id.desc())
                        .limit(1)
                        .scalar()
                )
                game_id = (last_game_id + 1) if last_game_id is not None else 1
                game = Game(
                    server_id=server_id,
                    id=game_id,
                    name=game_name,
                    submitter=str(ctx.author)
                )

            # Search Steam for this game and save the info
            steam_game_info = search_steam_for_game(game_name)
            if steam_game_info is not None and \
                    "id" in steam_game_info:
                game.steam_id = steam_game_info["id"]
                game_price = await get_steam_game_price(game.steam_id)
                update_game_steam_prices_fields(game, game_price)

            # If this game has a Steam ID, for each user with a Steam ID, check if they have owned or played the game
            if game.steam_id:
                members = (
                    db_session.query(ServerMember)
                        .filter(ServerMember.server_id == server_id)
                        .filter(ServerMember.steam_id.isnot(None))
                        .all()
                )   # type: list[ServerMember]
                for member in members:
                    try:
                        owned_games = await get_owned_steam_games(member.steam_id)
                        update_database_game_user_data(db_session, server_id, game.id, member.user_id, game.steam_id, owned_games)
                    except NoAccessException as e:
                        await ctx.send(e.message)

            # Get multiplayer info from IGDB
            multiplayer_info = await get_multiplayer_info_from_igdb(self.bot, game_name)   # type: MultiplayerInfo
            if multiplayer_info is not None:
                if multiplayer_info.max_players_online > 0:
                    game.player_count = multiplayer_info.max_players_online
                if multiplayer_info.max_players_offline > 0:
                    game.local = True
                    if multiplayer_info.max_players_online == 0:
                        game.player_count = multiplayer_info.max_players_offline
                if multiplayer_info.campaign_coop is False:
                    if game.notes is None:
                        game.notes = []
                    game.notes.append("No co-op campaign.")

            db_session.add(game)

        await update_live_messages(self.bot, server_id)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="remove", help="Removes a game from the list. Example: !remove \"game name\".")
    async def remove_game(self, ctx, game_name):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        with db_session_scope() as db_session:
            game = get_game(db_session, server_id, game_name)

            # Remove the game from the database
            db_session.delete(game)

        await update_live_messages(self.bot, server_id)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="finish", help="Marks a game as finished, moving it to the completed games list. Example: !finish \"game name\".")
    async def finish_game(self, ctx, game_name):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        with db_session_scope() as db_session:
            game = get_game(db_session, server_id, game_name)

            game.finished = True
            game.finished_timestamp = time.time()

            hog_message = await get_live_message_object(self.bot, server_id, LiveMessageType.HALL_OF_GAME)
            if hog_message:
                hog_channel = hog_message.channel
            else:
                hog_channel = ctx.channel

            game_text = game.name
            if game.steam_id is not None:
                game_link = f"https://store.steampowered.com/app/{game.steam_id}"
                game_text = f"[{game_text}](<{game_link}>)"     # Surround the link in <> to prevent a link embed from being added

            # Create a thread for the game and its screenshots in the hall of game channel
            banner_file = get_steam_game_banner(game.steam_id)
            if banner_file is None:
                banner_message = await hog_channel.send(game_text)
            else:
                banner_message = await hog_channel.send(game_text, file=banner_file)
            await banner_message.create_thread(name=game.name)
            await hog_channel.create_thread(name=f"{game.name} screenshots", type=discord.ChannelType.public_thread)

        await update_live_messages(self.bot, server_id)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="enjoyed", help="Rate how much you enjoyed a game, between 0-10. Example: !enjoyed \"game name\" 7.5. Default rating is 5.")
    async def enjoyed(self, ctx, game_name, score=5.0):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id
        user_id = ctx.author.id

        try:
            score = float(score)
            assert 0 <= score <= 10
        except (ValueError, AssertionError):
            await ctx.send("Rating must be a number between 0 and 10.")
            return

        with db_session_scope() as db_session:
            game = get_game(db_session, server_id, game_name, finished=True)
            game_user_data = db_session.get(GameUserData, (server_id, game.id, user_id))    # type: GameUserData
            if game_user_data is None:
                game_user_data = GameUserData(server_id=server_id, game_id=game.id, user_id=user_id)
                db_session.add(game_user_data)

            game_user_data.enjoyment_score = score

        await update_hall_of_game(self.bot, server_id)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="hog", help=":boar:")
    async def hall_of_game(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        hog_embed = await generate_hog_embed(ctx.guild.id)
        if hog_embed is None:
            await ctx.send("Nothing to show (yet).")
            return

        message = await ctx.send(embed=hog_embed)   # type: discord.Message

        with db_session_scope() as db_session:
            hog_live_message = LiveMessage(
                server_id=server_id,
                channel_id=message.channel.id,
                message_id=message.id,
                message_type=LiveMessageType.HALL_OF_GAME,
            )
            db_session.add(hog_live_message)

        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="vote", help="Sets your preference for playing a game, between 0-10. Example: !vote \"game name\" 7.5. Default vote is 5.")
    async def vote_game(self, ctx, game_name, score=5.0):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id
        user_id = ctx.author.id

        try:
            score = float(score)
            assert 0 <= score <= 10
        except (ValueError, AssertionError):
            await ctx.send("Score must be a number between 0 and 10.")
            return

        with db_session_scope() as db_session:
            game = get_game(db_session, server_id, game_name)
            game_user_data = db_session.get(GameUserData, (server_id, game.id, user_id))  # type: GameUserData
            if game_user_data is None:
                game_user_data = GameUserData(server_id=server_id, game_id=game.id, user_id=user_id)
                db_session.add(game_user_data)

            game_user_data.vote = score

        await update_live_messages(self.bot, server_id)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="list", help="Displays a sorted list of all games. Example: !list.")
    async def list_games(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        user_ids = [member.user_id for member in get_server_members(server_id)]

        # Remove the buttons from the old list message
        list_message_old = await get_live_message_object(self.bot, server_id, LiveMessageType.LIST)
        if list_message_old is not None:
            await list_message_old.edit(view=None)

            with db_session_scope() as db_session:
                # Delete the old list message from the database
                list_live_message_old = db_session.get(LiveMessage, list_message_old.id)    # type: LiveMessage
                if list_live_message_old is not None:
                    db_session.delete(list_live_message_old)

        list_embed = (await generate_list_embeds(server_id, user_ids))[0]
        embeds = [list_embed]
        filter_embed = generate_filter_embed(server_id)
        if filter_embed is not None:
            embeds.append(filter_embed)
        unvoted_embed = generate_unvoted_embed(server_id)
        if unvoted_embed is not None:
            embeds.append(unvoted_embed)

        list_message = await ctx.send(embeds=embeds)
        list_view = ListView(self.bot, list_embed.title, list_message.id, update_list, server_id)
        await list_message.edit(embeds=embeds, view=list_view)

        with db_session_scope() as db_session:
            list_live_message = LiveMessage(
                server_id=server_id,
                channel_id=list_message.channel.id,
                message_id=list_message.id,
                message_type=LiveMessageType.LIST,
                selected_user_ids=user_ids
            )
            db_session.add(list_live_message)

        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="owned_games", help="Displays a list of games that everyone has marked as owned. Example: !owned_games.")
    async def display_owned_games(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        owned_games_embed = generate_owned_games_embed(server_id)

        await ctx.send(embed=owned_games_embed)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="edit", help="Displays the given game as a message to be able edit it using its reactions. Example: !edit \"game name\".")
    async def edit(self, ctx, game_name):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        with db_session_scope() as db_session:
            game = get_game(db_session, server_id, game_name)

        edit_game = EditGame(self.bot, game.server_id, game.id, ctx.channel.id)
        await edit_game.send_message()

        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="unvoted", help="Shows you which games you haven't voted on yet. Example: !unvoted.")
    async def unvoted(self, ctx):
        log(f"{ctx.author}: {ctx.message.content}")

        unvoted_games = UnvotedGames(self.bot, ctx.guild, ctx.author)
        await unvoted_games.send_message()

        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="add_note", help="Adds an informative note to a game. Example: !add_note \"game name\" \"PvP only\".")
    async def add_note(self, ctx, game_name, note_text):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        with db_session_scope() as db_session:
            game = get_game(db_session, server_id, game_name)

            game.notes.append(note_text)

        await update_live_messages(self.bot, server_id)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="remove_note", help="Removes a note from a game. Example: !remove_note \"game name\" \"PvP only\".")
    async def remove_note(self, ctx, game_name, note_text):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        with db_session_scope() as db_session:
            game = get_game(db_session, server_id, game_name)

            if note_text not in game.notes:
                await ctx.send(f"Game \"{game.name}\" does not have note \"{note_text}\".")
                return

            game.notes.remove(note_text)

        await update_live_messages(self.bot, server_id)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="steam_id", help="Links a game to a steam ID for the purpose of retrieving prices. Example: !steam_id \"game name\" 105600.")
    async def set_steam_id(self, ctx, game_name, steam_id):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        try:
            steam_id = int(steam_id)
            assert steam_id >= 0
        except (ValueError, AssertionError):
            await ctx.send("Steam ID must be a positive number.")
            return

        with db_session_scope() as db_session:
            game = get_game(db_session, server_id, game_name)

            # Update the "steam_id" field, retrieve the price again, and save the new game data
            game.steam_id = steam_id
            steam_game_info = await get_steam_game_price(steam_id)
            update_game_steam_prices_fields(game, steam_game_info)

        await update_live_messages(self.bot, server_id)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="alias", help="Sets an alias for yourself, to be displayed in the list. Example: !alias :sunglasses:. Leave empty to clear it.")
    async def set_alias(self, ctx, new_alias=None):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id
        user_id = ctx.author.id

        with db_session_scope() as db_session:
            server_member = db_session.get(ServerMember, (user_id, server_id))  # type: ServerMember

            server_member.alias = new_alias

        await update_live_messages(self.bot, server_id)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="rename", help="Change the name of a game. Example: !rename \"game name\" \"new game name\".")
    async def rename_game(self, ctx, game_name, new_game_name):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id

        with db_session_scope() as db_session:
            game = get_game(db_session, server_id, game_name)

            game.name = new_game_name

        await update_live_messages(self.bot, server_id)
        await delete_message(ctx.message)

    @guild_only()
    @commands.command(name="link_steam", help="Link your Steam account to automatically fetch owned and played games. Accepts a Steam profile ID or custom URL ID. Example: !link_steam 76561198071149263.")
    async def link_steam_account(self, ctx, steam_profile_id):
        log(f"{ctx.author}: {ctx.message.content}")
        server_id = ctx.guild.id
        user_id = ctx.author.id

        try:
            steam_user_id = int(steam_profile_id)
        except ValueError:
            steam_user_id = await get_steam_user_id(steam_profile_id)

        owned_games = await get_owned_steam_games(steam_user_id)

        with db_session_scope() as db_session:
            server_member = db_session.get(ServerMember, (user_id, server_id))  # type: ServerMember

            # Save the Steam ID for this user in the database
            server_member.steam_id = steam_user_id

            update_database_games_with_steam_user_data(db_session, server_id, user_id, owned_games)

        await update_live_messages(self.bot, server_id)
        await delete_message(ctx.message)
