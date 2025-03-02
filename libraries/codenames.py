import json
import os
import random
import traceback
from abc import ABC, abstractmethod
import uuid
from io import BytesIO
import discord
from discord import ButtonStyle, DMChannel, ui, Interaction
from discord.ext.commands import Bot, Context
from discord.ui import View, Button, Modal, Select
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageOps

library_dir = os.path.dirname(os.path.abspath(__file__))

load_dotenv()
DEVELOPER_USER_ID = os.getenv("DEVELOPER_USER_ID")

CODENAMES_WORDS_FILE = os.path.join(library_dir, "codenames_words.txt")
MESSAGE_TO_GAME_MAPPING_FILE = os.path.join(library_dir, "message_to_game_mapping.json")
GAME_INFO_FILE = os.path.join(library_dir, "game_info.json")
USER_SETTINGS_FILE = os.path.join(library_dir, "user_settings.json")

# Values for visualizing the cards
CARD_CORNER_RADIUS = 25
CARD_BORDER_WIDTH = 4
CARD_PADDING = 10
TEXT_PADDING = 20
BASE_FONT_SIZE = 28
MIN_FONT_SIZE = 12
CARD_SIZE = (200, 150)
CARD_COVER_FILENAME = os.path.join(library_dir, "card_cover.png")
CARD_FONT_FILENAME = os.path.join(library_dir, "arialroundedmtbold.ttf")


async def get_discord_user(bot: Bot, user_id) -> discord.User:
    user = bot.get_user(int(user_id))
    if user is None:
        user = await bot.fetch_user(int(user_id))
    return user


async def send_error_message(bot, exception):
    print(traceback.print_exc(exception))
    print(exception)
    developer = await get_discord_user(bot, DEVELOPER_USER_ID)
    await developer.send(f"{type(exception)}: {exception}\n{traceback.print_exc(exception)}")


user_id_to_user_name = {}


async def get_user_name(bot, user_id):
    if user_id in user_id_to_user_name:
        return user_id_to_user_name[user_id]

    user_name = (await get_discord_user(bot, user_id)).global_name
    user_id_to_user_name[user_id] = user_name
    return user_name


def get_words():
    words = []
    with open(CODENAMES_WORDS_FILE, "r") as file:
        for line in file:
            words.append(line.strip().upper())

    return words


def read_file_safe(filename):
    if not os.path.exists(filename):
        print(f"{filename} does not exist. Creating it...")
        file_data = {}
    else:
        with open(filename, "r") as file:
            file_data = json.load(file)

    return file_data


def load_games(bot: Bot):
    game_info_dict = read_file_safe(GAME_INFO_FILE)
    for game_uuid, game_info in game_info_dict.items():
        if game_info["setup"]:
            game_object = GameSetup(bot, json_data=game_info)
        else:
            game_object = Game(bot=bot, json_data=game_info)


class CodenamesException(Exception):

    message = ""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class CardType:
    NEUTRAL = "neutral"
    RED = "red"
    BLUE = "blue"
    ASSASSIN = "assassin"


CARD_TYPE_TO_BUTTON_COLOR = {
    CardType.NEUTRAL: ButtonStyle.grey,
    CardType.RED: ButtonStyle.red,
    CardType.BLUE: ButtonStyle.blurple,
    CardType.ASSASSIN: ButtonStyle.green,
}

CARD_TYPE_TO_EMOJI = {
    CardType.NEUTRAL: "⬜",
    CardType.RED: "🟥",
    CardType.BLUE: "🟦",
    CardType.ASSASSIN: "💀",
}

# Define the colors used to display the cards
CARD_TYPE_TO_RGB_COLOR = {
    CardType.RED: (220, 60, 60),
    CardType.BLUE: (20, 125, 200),
    CardType.ASSASSIN: (50, 50, 50),
    CardType.NEUTRAL: (220, 215, 210),
}


class Card:

    def __init__(self, word=None, card_type=None, json_data=None):
        if json_data:
            self.load_json(json_data)
            return

        self.word = word.upper()
        self.type = card_type
        self.tapped = False

    def load_json(self, json_data):
        self.word = json_data["word"]
        self.type = json_data["type"]
        self.tapped = json_data["tapped"]

    def get_word_formatted(self, length: int):
        remaining_length = int((length - len(self.word))/2)
        word = "_" * remaining_length + self.word + "_" * remaining_length
        return word

    def to_dict(self):
        return {
            "word": self.word,
            "type": self.type,
            "tapped": self.tapped,
        }


class PlayerRole:
    RED_SPYMASTER = "red spymaster"
    RED_OPERATIVE = "red operative"
    BLUE_SPYMASTER = "blue spymaster"
    BLUE_OPERATIVE = "blue operative"
    RANDOM = "random"


class TeamColor:
    RED = "red"
    BLUE = "blue"


PLAYER_ROLE_TO_COLOR = {
    PlayerRole.RED_SPYMASTER: TeamColor.RED,
    PlayerRole.RED_OPERATIVE: TeamColor.RED,
    PlayerRole.BLUE_SPYMASTER: TeamColor.BLUE,
    PlayerRole.BLUE_OPERATIVE: TeamColor.BLUE,
}


PLAYER_ROLES = vars(PlayerRole).values()


class DiscordMessage:

    def __init__(self, bot, channel_id=None, message_id=None, json_data=None):
        self.bot = bot

        if json_data is not None:
            self.load_json(json_data)
            return

        self.channel_id = channel_id
        self.message_id = message_id

    def load_json(self, json_data):
        self.channel_id = json_data["channel_id"]
        self.message_id = json_data["message_id"]

    def to_dict(self):
        return {
            "channel_id": self.channel_id,
            "message_id": self.message_id,
        }

    def get_channel_object(self):
        return self.bot.get_channel(self.channel_id)

    async def get_message(self) -> discord.Message:
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                raise Exception(f"Could not find channel with ID {self.channel_id}.")

            return await channel.fetch_message(self.message_id)
        except Exception as e:
            await send_error_message(self.bot, e)


class ViewFormat:
    IMAGE = "image"
    BUTTONS = "buttons"


class UserSettings:

    def __init__(self, bot: Bot, user_id):
        self.bot = bot
        self.user_id = str(user_id)
        self.discord_message = None

        user_settings = read_file_safe(USER_SETTINGS_FILE).get(self.user_id, {})
        self.view_format = user_settings.get("view_format", ViewFormat.IMAGE)

    def to_dict(self):
        return {
            "view_format": self.view_format,
        }

    def save_to_file(self, json_dict=None):
        if json_dict is None:
            json_dict = self.to_dict()

        all_settings = read_file_safe(USER_SETTINGS_FILE)
        all_settings[self.user_id] = json_dict
        with open(USER_SETTINGS_FILE, "w") as file:
            json.dump(all_settings, file, indent=4)

    async def send_message(self):
        user = await get_discord_user(self.bot, self.user_id)
        embed = await self.get_embed()
        view = self.SettingsView(self)
        message_object = await user.send(embed=embed, view=view)    # type: discord.Message
        self.discord_message = DiscordMessage(self.bot, message_object.channel.id, message_object.id)

    async def get_embed(self):
        description = ""
        description += f"View format: **{self.view_format}**\n"
        embed = discord.Embed(
            title="Codenames settings",
            description=description,
            color=discord.Color.brand_green()
        )
        return embed

    async def set_setting(self, setting, value):
        setattr(self, setting, value)

        # Update the settings message
        embed = await self.get_embed()
        view = self.SettingsView(self)
        message_object = await self.discord_message.get_message()
        await message_object.edit(embed=embed, view=view)

        self.save_to_file()

    class SettingsView(View):

        def __init__(self, settings):
            super().__init__(timeout=None)
            self.settings = settings

            self.add_item(self.settings.ViewFormatSelectMenu(self.settings))
            # self.add_item(Button(style=ButtonStyle.gray, label="Change view format", custom_id=f"view_format"))

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            try:
                user_id = interaction.user.id
                button_id = interaction.data.get("custom_id")

                # noinspection PyUnresolvedReferences
                await interaction.response.defer()
            except CodenamesException as e:
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(str(e), ephemeral=True)
            except Exception as e:
                await send_error_message(self.user_settings.bot, e)

            return True

    class ViewFormatSelectMenu(Select):
        def __init__(self, settings):
            self.settings = settings
            options = []
            for key, value in vars(ViewFormat).items():
                if key.isupper() and isinstance(value, str):
                    options.append(discord.SelectOption(label=value, value=value))
            super().__init__(placeholder="View format", options=options)

        async def callback(self, interaction: discord.Interaction):
            selected_format = self.values[0]
            await self.settings.set_setting("view_format", selected_format)


class BaseGameClass(ABC):

    def __init__(self, bot: Bot):
        self.bot = bot
        self.uuid = str(uuid.uuid4())
        self.discord_messages = []  # type: list[DiscordMessage]

    @abstractmethod
    def to_dict(self):
        pass

    async def delete_messages(self):
        for discord_message in self.discord_messages:
            message_object = await discord_message.get_message()
            await message_object.delete()

    def save_to_file(self):
        message_to_game_mapping = read_file_safe(MESSAGE_TO_GAME_MAPPING_FILE)
        for message in self.discord_messages:
            message_to_game_mapping[message.message_id] = self.uuid
        with open(MESSAGE_TO_GAME_MAPPING_FILE, "w") as file:
            json.dump(message_to_game_mapping, file, indent=4)

        game_info = read_file_safe(GAME_INFO_FILE)
        game_info[self.uuid] = self.to_dict()
        with open(GAME_INFO_FILE, "w") as file:
            json.dump(game_info, file, indent=4)

    def remove_from_file(self):
        message_to_game_mapping = read_file_safe(MESSAGE_TO_GAME_MAPPING_FILE)
        for message in self.discord_messages:
            message_to_game_mapping.pop(message.message_id, None)
        with open(MESSAGE_TO_GAME_MAPPING_FILE, "w") as file:
            json.dump(message_to_game_mapping, file, indent=4)

        game_setup_info = read_file_safe(GAME_INFO_FILE)
        game_setup_info.pop(self.uuid, None)
        with open(GAME_INFO_FILE, "w") as file:
            json.dump(game_setup_info, file, indent=4)


class GameSetup(BaseGameClass):

    def __init__(self, bot: Bot, json_data=None):
        super().__init__(bot)
        if json_data is not None:
            self.load_json(json_data)
            for prefix in self.message_custom_id_prefixes:
                self.bot.add_view(self.GameSetupView(self, prefix))
            return

        # Info referencing the messages that are displaying this object
        self.discord_messages = []   # type: list[DiscordMessage]
        self.message_custom_id_prefixes = []

        # The user ID of each player and what role they picked
        self.roles = {
            PlayerRole.RED_SPYMASTER: 0,
            PlayerRole.RED_OPERATIVE: 0,
            PlayerRole.BLUE_SPYMASTER: 0,
            PlayerRole.BLUE_OPERATIVE: 0,
        }   # type: dict[str, int]
        self.random_role = []   # type: list[int]

    def load_json(self, json_data):
        self.uuid = json_data["uuid"]
        self.discord_messages = [DiscordMessage(self.bot, json_data=msg) for msg in json_data["discord_messages"]]
        self.message_custom_id_prefixes = [prefix for prefix in json_data["message_custom_id_prefixes"]]
        self.roles = json_data["roles"]
        self.random_role = json_data["random_role"]

    def to_dict(self):
        return {
            "setup": True,
            "uuid": self.uuid,
            "discord_messages": [msg.to_dict() for msg in self.discord_messages],
            "message_custom_id_prefixes": [prefix for prefix in self.message_custom_id_prefixes],
            "roles": self.roles,
            "random_role": self.random_role,
        }

    def _remove_user_role(self, user_id: int):
        if user_id in self.random_role:
            self.random_role.remove(user_id)

        for role, player in self.roles.items():
            if player == user_id:
                self.roles[role] = 0

    async def join_role(self, role, user_id: int):
        # First take care of the "random" role use case
        if role == PlayerRole.RANDOM:
            if user_id in self.random_role:
                return
            self._remove_user_role(user_id)
            self.random_role.append(user_id)
        else:
            if self.roles[role] == user_id:
                return  # The user already belongs to this role
            if self.roles[role] != 0:
                raise CodenamesException(f"The {role} role is already taken by someone else.")
            self._remove_user_role(user_id)
            self.roles[role] = user_id

        # Update the messages to reflect the changes
        await self.update_messages()

        if self.get_player_count() >= 4:
            await self.start_game()

    def get_player_count(self):
        return sum(1 for user_id in self.roles.values() if user_id != 0) + len(self.random_role)

    def distribute_random_players(self):
        unfilled_roles = [role for role, user_id in self.roles.items() if user_id == 0]
        random.shuffle(self.random_role)
        for user_id in self.random_role:
            role = unfilled_roles.pop(0)
            self.roles[role] = user_id

    async def send_new_message(self, ctx: Context):
        embed = await self.get_embed()
        channel_id = ctx.channel.id
        view = self.GameSetupView(self, channel_id)
        self.message_custom_id_prefixes.append(channel_id)
        message_object = await ctx.send(embed=embed, view=view)    # type: discord.Message
        self.discord_messages.append(DiscordMessage(self.bot, message_object.channel.id, message_object.id))
        self.save_to_file()
        return message_object

    async def send_new_user_messages(self, user_ids: list[int], name=""):
        try:
            if name:
                embed = await self.get_embed(f"{name} has requested a rematch.")
            else:
                embed = await self.get_embed()
            self.discord_messages = []
            for user_id in user_ids:
                user = await get_discord_user(self.bot, user_id)
                view = self.GameSetupView(self, user_id)
                self.message_custom_id_prefixes.append(user_id)
                message_object = await user.send(embed=embed, view=view)    # type: discord.Message
                self.discord_messages.append(DiscordMessage(self.bot, message_object.channel.id, message_object.id))
            self.save_to_file()
        except Exception as e:
            await send_error_message(self.bot, e)

    async def update_messages(self):
        embed = await self.get_embed()
        for discord_message in self.discord_messages:
            message_object = await discord_message.get_message()
            await message_object.edit(embed=embed)
        self.save_to_file()

    async def start_game(self):
        if self.get_player_count() < 4:
            raise CodenamesException("Not enough players to start the game!")
        self.distribute_random_players()
        game = Game(self)
        await game.send_new_messages_to_all_users()
        self.remove_from_file()
        await self.delete_messages()

    async def get_role_user(self, role):
        if role == PlayerRole.RANDOM:
            return "\n".join([await get_user_name(self.bot, user_id) for user_id in self.random_role])

        user_id = self.roles[role]
        if user_id == 0:
            return ""
        return await get_user_name(self.bot, user_id)

    async def get_embed(self, description="Choose a role."):
        embed = discord.Embed(
            title="Codenames",
            description=description,
            color=discord.Color.dark_green()
        )
        embed.add_field(name="Red Spymaster", value=await self.get_role_user(PlayerRole.RED_SPYMASTER), inline=True)
        embed.add_field(name="Random", value=await self.get_role_user(PlayerRole.RANDOM), inline=True)
        embed.add_field(name="Blue Spymaster", value=await self.get_role_user(PlayerRole.BLUE_SPYMASTER), inline=True)
        embed.add_field(name="Red Operative", value=await self.get_role_user(PlayerRole.RED_OPERATIVE), inline=True)
        embed.add_field(name="", value="", inline=True)
        embed.add_field(name="Blue Operative", value=await self.get_role_user(PlayerRole.BLUE_OPERATIVE), inline=True)
        return embed

    class GameSetupView(View):

        def __init__(self, game_setup, prefix):
            super().__init__(timeout=None)
            self.game_setup = game_setup    # type: GameSetup

            self.add_item(Button(style=ButtonStyle.red, label="Red Spymaster", custom_id=f"{self.game_setup.uuid}_{prefix}_{PlayerRole.RED_SPYMASTER}"))
            self.add_item(Button(style=ButtonStyle.red, label="Red Operative", custom_id=f"{self.game_setup.uuid}_{prefix}_{PlayerRole.RED_OPERATIVE}"))
            self.add_item(Button(style=ButtonStyle.gray, label="Random", custom_id=f"{self.game_setup.uuid}_{prefix}_{PlayerRole.RANDOM}"))
            self.add_item(Button(style=ButtonStyle.blurple, label="Blue Spymaster", custom_id=f"{self.game_setup.uuid}_{prefix}_{PlayerRole.BLUE_SPYMASTER}"))
            self.add_item(Button(style=ButtonStyle.blurple, label="Blue Operative", custom_id=f"{self.game_setup.uuid}_{prefix}_{PlayerRole.BLUE_OPERATIVE}"))

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            try:
                user_id = interaction.user.id
                role = interaction.data.get("custom_id").split("_")[-1]
                await self.game_setup.join_role(role, user_id)
                # noinspection PyUnresolvedReferences
                await interaction.response.defer()
            except CodenamesException as e:
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(str(e), ephemeral=True)
            except Exception as e:
                await send_error_message(self.game_setup.bot, e)

            return True


async def create_new_game(ctx: Context):
    game_setup = GameSetup(ctx.bot)
    await game_setup.send_new_message(ctx)
    return game_setup


async def show_settings(ctx: Context):
    user_id = str(ctx.author.id)
    settings = UserSettings(ctx.bot, user_id)
    await settings.send_message()


class Game(BaseGameClass):

    def __init__(self, game_setup: GameSetup = None, bot: Bot = None, json_data=None):
        bot = bot if bot else game_setup.bot
        super().__init__(bot)
        self.finished = False
        if json_data is not None:
            self.load_json(json_data)
            for role in self.roles.keys():
                self.bot.add_view(self.GameView(self, role))
            return

        self.turn = 1
        self.roles = game_setup.roles   # type: dict[str, int]

        self.history = {
            PlayerRole.RED_SPYMASTER: [],
            PlayerRole.RED_OPERATIVE: [],
            PlayerRole.BLUE_SPYMASTER: [],
            PlayerRole.BLUE_OPERATIVE: [],
        }
        self.starting_team = random.choice([TeamColor.RED, TeamColor.BLUE])

        self.turn_order = self.determine_turn_order()
        self.cards = self.generate_cards()
        self.guess_count = 0
        self.clue_word = ""
        self.clue_amount = 0
        self.max_word_length = self.get_max_word_length()

    def load_json(self, json_data):
        self.uuid = json_data.get("uuid")
        self.turn = json_data.get("turn")
        self.roles = json_data["roles"]
        self.history = json_data["history"]
        self.starting_team = json_data["starting_team"]
        self.turn_order = json_data["turn_order"]
        self.cards = json_data["cards"]
        self.cards = [Card(json_data=card) for card in json_data["cards"]]
        self.guess_count = json_data["guess_count"]
        self.max_word_length = self.get_max_word_length()

    def to_dict(self):
        return {
            "setup": False,
            "uuid": self.uuid,
            "turn": self.turn,
            "roles": self.roles,
            "history": self.history,
            "starting_team": self.starting_team,
            "turn_order": self.turn_order,
            "cards": [card.to_dict() for card in self.cards],
            "guess_count": self.guess_count,
        }

    def get_max_word_length(self):
        max_word_length = 0
        for card in self.cards:
            if len(card.word) > max_word_length:
                max_word_length = len(card.word)
        return max_word_length

    def generate_cards(self):
        words = random.sample(get_words(), 25)
        words_first_team = random.sample(words, 9)
        remaining_words = [word for word in words if word not in words_first_team]
        words_second_team = random.sample(remaining_words, 8)
        remaining_words = [word for word in remaining_words if word not in words_second_team]
        word_assassin = random.choice(remaining_words)
        words_neutral = [word for word in remaining_words if word != word_assassin]

        cards = []
        for word in words_first_team:
            if self.starting_team == TeamColor.RED:
                cards.append(Card(word, CardType.RED))
            else:
                cards.append(Card(word, CardType.BLUE))
        for word in words_second_team:
            if self.starting_team == TeamColor.RED:
                cards.append(Card(word, CardType.BLUE))
            else:
                cards.append(Card(word, CardType.RED))
        cards.append(Card(word_assassin, CardType.ASSASSIN))
        for word in words_neutral:
            cards.append(Card(word, CardType.NEUTRAL))

        random.shuffle(cards)
        return cards

    def determine_turn_order(self):
        if self.starting_team == TeamColor.RED:
            return [PlayerRole.RED_SPYMASTER, PlayerRole.RED_OPERATIVE, PlayerRole.BLUE_SPYMASTER, PlayerRole.BLUE_OPERATIVE]
        else:
            return [PlayerRole.BLUE_SPYMASTER, PlayerRole.BLUE_OPERATIVE, PlayerRole.RED_SPYMASTER, PlayerRole.RED_OPERATIVE]

    def generate_image(self, is_spymaster=False, reveal_covered=False):
        # Load the image used to cover guessed cards
        card_cover_template = Image.open(CARD_COVER_FILENAME).convert("RGBA")

        # Load the font
        font = ImageFont.truetype(CARD_FONT_FILENAME)

        # Create a new mask for the cards
        card_mask = Image.new("L", CARD_SIZE)    # "L" is greyscale
        # Draw a rectangle with rounded corners on the mask
        draw_mask = ImageDraw.Draw(card_mask)
        draw_mask.rounded_rectangle([(0, 0), CARD_SIZE], CARD_CORNER_RADIUS, fill=255)

        # Calculate and create a transparent image with the required size to hold the whole board
        grid_size = 5
        total_width = grid_size * (CARD_SIZE[0] + CARD_PADDING) - CARD_PADDING
        total_height = grid_size * (CARD_SIZE[1] + CARD_PADDING) - CARD_PADDING
        board = Image.new("RGBA", (total_width, total_height), (0, 0, 0, 0))

        for i, card in enumerate(self.cards):
            # Calculate this card's position in the image
            row, col = divmod(i, grid_size)
            x = col * (CARD_SIZE[0] + CARD_PADDING)
            y = row * (CARD_SIZE[1] + CARD_PADDING)

            # Create the base of the card
            bg_color = CARD_TYPE_TO_RGB_COLOR.get(CardType.NEUTRAL)
            if is_spymaster or card.tapped:
                bg_color = CARD_TYPE_TO_RGB_COLOR.get(card.type)
            card_bg = Image.new("RGBA", CARD_SIZE, bg_color)

            # Prepare to start drawing on the card
            draw_card = ImageDraw.Draw(card_bg)

            # Determine if the text should be displayed in white or black, depending on the background's brightness
            text_color = (35, 35, 35, 255)
            bg_brightness = 0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2]  # Calculates perceived brightness
            if bg_brightness < 150:
                text_color = (245, 245, 245, 255)

            # Resize the text to fit in the card, if necessary
            card_text = card.word.upper()
            font_size = BASE_FONT_SIZE
            font = font.font_variant(size=font_size)    # Copy the font with a different font size
            text_bbox = draw_card.textbbox((0, 0), card_text, font=font)
            while font_size > MIN_FONT_SIZE and (text_bbox[2] - text_bbox[0]) > CARD_SIZE[0] - TEXT_PADDING:
                font_size -= 1
                # Check the size of the word with a specific font size
                font = font.font_variant(size=font_size)
                text_bbox = draw_card.textbbox((0, 0), card_text, font=font)
            # Draw the text on the card
            text_position = (
                (CARD_SIZE[0] - (text_bbox[2] - text_bbox[0])) // 2,
                (CARD_SIZE[1] - (text_bbox[3] - text_bbox[1])) // 2
            )
            draw_card.text(text_position, card_text, fill=text_color, font=font)

            # If a card is guessed, cover it
            if card.tapped:
                # Creates a greyscale copy of the cover template
                cover = card_cover_template.resize(CARD_SIZE).convert("L")

                # Mirror the cover image if it's an assassin card (for extra clarity)
                if card.type == CardType.ASSASSIN:
                    cover = cover.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

                # The cover is colorized to match the card's type
                cover_color = CARD_TYPE_TO_RGB_COLOR.get(card.type)
                cover = ImageOps.colorize(
                    cover,
                    black="black",
                    white=cover_color
                ).convert("RGBA")

                # Make the cover transparent if we need to reveal the covered cards
                alpha = 128 if reveal_covered else 255
                alpha_layer = Image.new("L", CARD_SIZE, alpha)
                cover.putalpha(alpha_layer)

                # Add the cover on top of the card
                card_bg.alpha_composite(cover)

            # Remove pixels so that the card fits the card mask
            card_bg = Image.composite(
                card_bg,
                Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0)),     # Empty image
                card_mask
            )

            # Add a border (matching the card's rounded corners) to the card
            border = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
            draw_border = ImageDraw.Draw(border)
            draw_border.rounded_rectangle(
                [(0, 0), CARD_SIZE],
                CARD_CORNER_RADIUS,
                outline=(0, 0, 0, 40),  # Darkened/transparent borders
                width=CARD_BORDER_WIDTH
            )
            card_bg.alpha_composite(border)

            # Add the card to the board on the correct position
            board.alpha_composite(card_bg, dest=(x, y))

        # Save the board image in memory and return it
        board_image = BytesIO()
        board.save(board_image, format="PNG")
        board_image.seek(0)  # Set buffer position to the start so the data will be read from there
        return board_image

    def add_history(self, line):
        for role in self.history.keys():
            self.history[role].append(line)

    async def get_history_for_role(self, role, is_final_message_edit):
        history = self.history[role].copy()
        if self.is_game_finished(add_history=False) or is_final_message_edit:
            return "\n".join(history)

        current_role = self.turn_order[0]
        current_color = PLAYER_ROLE_TO_COLOR[current_role]
        current_player = await self.get_role_user_name(current_role)
        if current_role == role:
            if current_role in [PlayerRole.RED_SPYMASTER, PlayerRole.BLUE_SPYMASTER]:
                history.append(f"Please think of a clue for the {current_color} team. Click any card when you are ready to enter the clue.")
            else:
                history.append(f"Please choose cards matching the given clue. Click on any card that has already been revealed to end your turn.")
        else:
            if current_role in [PlayerRole.RED_SPYMASTER, PlayerRole.BLUE_SPYMASTER]:
                history.append(f"{current_player} is currently thinking of a clue for the {current_color} team...")
            else:
                history.append(f"{current_player} is currently choosing cards for the {current_color} team...")
        return "\n".join(history)

    async def get_role_user_name(self, role):
        user_id = self.roles[role]
        return (await get_discord_user(self.bot, user_id)).global_name

    def get_user_role(self, user_id):
        for role, role_user_id in self.roles.items():
            if user_id == role_user_id:
                return role
        raise Exception(f"Could not find user ID {user_id} in roles: {self.roles}.")

    def get_card(self, word):
        for card in self.cards:
            if card.word == word:
                return card

    async def give_clue(self, user_id, given_clue, number):
        role = self.get_user_role(user_id)
        if role != self.turn_order[0]:
            raise CodenamesException("It is not your turn.")

        clue = given_clue.upper()
        try:
            number = int(number)
        except ValueError:
            raise CodenamesException(f"{number} is not a valid number.")

        current_role = self.turn_order[0]
        user_name = await self.get_role_user_name(current_role)
        team_color = PLAYER_ROLE_TO_COLOR[current_role]
        self.add_history(f"{user_name} gave the {team_color} team a clue: **{clue}** **{number}**.")
        self.clue_amount = number
        await self.next_turn()

    async def chose_word(self, word, user_id):
        card = self.get_card(word)
        role = self.get_user_role(user_id)
        user_name = await self.get_role_user_name(role)
        if card.tapped:
            # Interpret this as the player ending their turn
            if self.guess_count == 0:
                raise CodenamesException("You must choose at least one card each turn.")
            self.add_history(f"{user_name} finished guessing.")
            await self.next_turn()
            return

        card.tapped = True
        self.guess_count += 1
        card_emoji = CARD_TYPE_TO_EMOJI[card.type]
        self.add_history(f"{user_name} guessed **{card.word}{card_emoji}**.")
        if self.clue_amount != 0 and self.guess_count > self.clue_amount:
            if self.is_game_finished():
                self.end_game()
                await self.update_messages()
                return
            self.add_history(f"Reached maximum amount of guesses for this turn.")
            await self.next_turn()
        elif role == PlayerRole.RED_OPERATIVE and card.type == CardType.RED:
            if self.is_game_finished():
                self.end_game()
                await self.update_messages()
                return
            await self.update_messages()
        elif role == PlayerRole.BLUE_OPERATIVE and card.type == CardType.BLUE:
            if self.is_game_finished():
                self.end_game()
                await self.update_messages()
                return
            await self.update_messages()
        else:
            if self.is_game_finished():
                self.end_game()
                await self.update_messages()
                return
            await self.next_turn()

    async def choose_word(self, word, user_id, interaction: Interaction):
        card = self.get_card(word)
        if self.finished:
            if card.type != CardType.ASSASSIN:
                raise CodenamesException("This game has already ended. If you would like a rematch, click the assassin card.")
            else:
                game_setup = GameSetup(self.bot)
                user_ids = list(self.roles.values())
                user_name = (await get_discord_user(self.bot, user_id)).global_name
                await game_setup.send_new_user_messages(user_ids, user_name)
                return
        role = self.get_user_role(user_id)
        if role != self.turn_order[0]:
            raise CodenamesException("It is not your turn.")

        if role in [PlayerRole.RED_SPYMASTER, PlayerRole.BLUE_SPYMASTER]:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_modal(self.ClueModal(self))
        else:
            user_name = await self.get_role_user_name(role)
            if card.tapped:
                # Interpret this as the player ending their turn
                if self.guess_count == 0:
                    raise CodenamesException("You must choose at least one card each turn.")
                self.add_history(f"{user_name} finished guessing.")
                await self.next_turn()
                return

            card.tapped = True
            self.guess_count += 1
            card_emoji = CARD_TYPE_TO_EMOJI[card.type]
            self.add_history(f"{user_name} guessed **{card.word}{card_emoji}**.")
            if self.clue_amount != 0 and self.guess_count > self.clue_amount:
                if self.is_game_finished():
                    self.end_game()
                    await self.update_messages()
                    return
                self.add_history(f"Reached maximum amount of guesses for this turn.")
                await self.next_turn()
            elif role == PlayerRole.RED_OPERATIVE and card.type == CardType.RED:
                if self.is_game_finished():
                    self.end_game()
                    await self.update_messages()
                    return
                await self.update_messages()
            elif role == PlayerRole.BLUE_OPERATIVE and card.type == CardType.BLUE:
                if self.is_game_finished():
                    self.end_game()
                    await self.update_messages()
                    return
                await self.update_messages()
            else:
                if self.is_game_finished():
                    self.end_game()
                    await self.update_messages()
                    return
                await self.next_turn()

    def is_game_finished(self, add_history=True):
        guessed_red = 0
        guessed_blue = 0
        for card in self.cards:
            if card.tapped:
                if card.type == CardType.RED:
                    guessed_red += 1
                elif card.type == CardType.BLUE:
                    guessed_blue += 1
                elif card.type == CardType.ASSASSIN:
                    current_role = self.turn_order[0]
                    if add_history:
                        if current_role == PlayerRole.RED_OPERATIVE:
                            self.add_history(f"The red team picked the assassin, so the blue team wins.")
                        else:
                            self.add_history(f"The blue team picked the assassin, so the red team wins.")
                    return True

        if self.starting_team == TeamColor.RED:
            if guessed_red == 9:
                if add_history:
                    self.add_history(f"All the red cards have been guessed, so the red team wins.")
                return True
            elif guessed_blue == 8:
                if add_history:
                    self.add_history(f"All the blue cards have been guessed, so the blue team wins.")
                return True
        else:
            if guessed_red == 8:
                if add_history:
                    self.add_history(f"All the red cards have been guessed, so the red team wins.")
                return True
            elif guessed_blue == 9:
                if add_history:
                    self.add_history(f"All the blue cards have been guessed, so the blue team wins.")
                return True

        return False

    def end_game(self):
        self.finished = True
        self.add_history(f"The game has ended. Click the assassin card to request a rematch.")
        self.remove_from_file()

    async def next_turn(self):
        # Make sure the current messages are up-to-date
        await self.update_messages(is_final_message_edit=True)

        self.guess_count = 0
        # Move the first item to the end of the list
        self.turn_order.append(self.turn_order.pop(0))
        self.turn += 1

        await self.send_new_messages_to_all_users()

    def get_cards_left_string(self):
        if self.starting_team == TeamColor.RED:
            total_cards_red = 9
            total_cards_blue = 8
        else:
            total_cards_red = 8
            total_cards_blue = 9
        chosen_red_cards = sum(1 for card in self.cards if card.tapped and card.type == CardType.RED)
        chosen_blue_cards = sum(1 for card in self.cards if card.tapped and card.type == CardType.BLUE)
        remaining_red_cards = total_cards_red-chosen_red_cards
        remaining_blue_cards = total_cards_blue-chosen_blue_cards
        return f"{remaining_red_cards} - {remaining_blue_cards}"

    async def get_embed(self, role, is_final_message_edit):
        embed = discord.Embed(
            title="Codenames",
            description=await self.get_history_for_role(role, is_final_message_edit),
            color=discord.Color.dark_green()
        )
        current_role_turn = self.turn_order[0]
        # Show who's turn it is with an emoji
        rs_turn = " :arrow_left:" if current_role_turn == PlayerRole.RED_SPYMASTER else ""
        bs_turn = " :arrow_left:" if current_role_turn == PlayerRole.BLUE_SPYMASTER else ""
        ro_turn = " :arrow_left:" if current_role_turn == PlayerRole.RED_OPERATIVE else ""
        bo_turn = " :arrow_left:" if current_role_turn == PlayerRole.BLUE_OPERATIVE else ""

        embed.add_field(name="Red Spymaster", value=await self.get_role_user_name(PlayerRole.RED_SPYMASTER) + rs_turn, inline=True)
        embed.add_field(name="Cards left", value=self.get_cards_left_string(), inline=True)
        embed.add_field(name="Blue Spymaster", value=await self.get_role_user_name(PlayerRole.BLUE_SPYMASTER) + bs_turn, inline=True)
        embed.add_field(name="Red Operative", value=await self.get_role_user_name(PlayerRole.RED_OPERATIVE) + ro_turn, inline=True)
        embed.add_field(name="", value="", inline=True)
        embed.add_field(name="Blue Operative", value=await self.get_role_user_name(PlayerRole.BLUE_OPERATIVE) + bo_turn, inline=True)
        return embed

    async def send_new_messages_to_all_users(self):
        try:
            self.discord_messages = []
            for role, user_id in self.roles.items():
                self.history[role] = []
                embed = await self.get_embed(role, is_final_message_edit=False)
                user = await get_discord_user(self.bot, user_id)
                is_spymaster = role in [PlayerRole.RED_SPYMASTER, PlayerRole.BLUE_SPYMASTER] or self.finished
                file = discord.File(self.generate_image(is_spymaster), filename="codenames.png")
                message_object = await user.send(embed=embed, view=self.GameView(self, role), file=file)
                self.discord_messages.append(DiscordMessage(self.bot, message_object.channel.id, message_object.id))
            self.save_to_file()
        except Exception as e:
            await send_error_message(self.bot, e)

    async def update_messages(self, is_final_message_edit=False):
        for discord_message in self.discord_messages:
            channel_object = discord_message.get_channel_object()   # type: DMChannel
            user_id = channel_object.recipient.id

            role = self.get_user_role(user_id)
            embed = await self.get_embed(role, is_final_message_edit=is_final_message_edit)
            is_spymaster = role in [PlayerRole.RED_SPYMASTER, PlayerRole.BLUE_SPYMASTER] or self.finished
            file = discord.File(self.generate_image(is_spymaster), filename="codenames.png")
            message_object = await discord_message.get_message()
            await message_object.edit(embed=embed, view=self.GameView(self, role), attachments=[file])
        self.save_to_file()

    class CardSelectMenu(Select):
        def __init__(self, game, custom_id: str, disabled: bool):
            self.game = game
            options = []
            for card in self.game.cards:
                if card.tapped is False:
                    options.append(discord.SelectOption(label=card.word, value=card.word))
            super().__init__(placeholder="Choose a card...", options=options, custom_id=custom_id, disabled=disabled)

        async def callback(self, interaction: discord.Interaction):
            user_id = interaction.user.id
            await self.game.chose_word(self.values[0], user_id)

    class GameView(View):

        def __init__(self, game, role: str):
            super().__init__(timeout=None)
            self.game = game    # type: Game
            self.role = role

            disabled = True if role != self.game.turn_order[0] else False

            if self.game.finished:
                custom_id = f"{self.game.uuid}_{self.game.turn}_{self.role}_rematch"
                self.add_item(Button(style=ButtonStyle.grey, label="Rematch", custom_id=custom_id))
            elif self.role in [PlayerRole.RED_SPYMASTER, PlayerRole.BLUE_SPYMASTER]:
                custom_id = f"{self.game.uuid}_{self.game.turn}_{self.role}_enter-clue"
                self.add_item(Button(style=ButtonStyle.grey, label="Enter clue", custom_id=custom_id, disabled=disabled))
            else:
                custom_id = f"{self.game.uuid}_{self.game.turn}_{self.role}_choose-card"
                self.add_item(self.game.CardSelectMenu(self.game, custom_id=custom_id, disabled=disabled))

                end_turn_disabled = True if self.game.guess_count == 0 else False
                custom_id = f"{self.game.uuid}_{self.game.turn}_{self.role}_end-turn"
                self.add_item(Button(style=ButtonStyle.grey, label="End turn", custom_id=custom_id, disabled=end_turn_disabled))

            custom_id = f"{self.game.uuid}_{self.game.turn}_{self.role}_reveal-cards"
            self.add_item(Button(style=ButtonStyle.grey, label="Reveal cards", custom_id=custom_id))
            custom_id = f"{self.game.uuid}_{self.game.turn}_{self.role}_cover-cards"
            self.add_item(Button(style=ButtonStyle.grey, label="Cover cards", custom_id=custom_id))

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            try:
                user_id = interaction.user.id
                user_name = (await get_discord_user(self.game.bot, user_id)).global_name
                action = interaction.data.get("custom_id").split("_")[-1]
                if action == "reveal-cards":
                    role = self.game.get_user_role(user_id)
                    is_spymaster = role in [PlayerRole.RED_SPYMASTER, PlayerRole.BLUE_SPYMASTER] or self.game.finished
                    file = discord.File(self.game.generate_image(is_spymaster, reveal_covered=True), filename="codenames.png")
                    await interaction.message.edit(attachments=[file])
                elif action == "cover-cards":
                    role = self.game.get_user_role(user_id)
                    is_spymaster = role in [PlayerRole.RED_SPYMASTER, PlayerRole.BLUE_SPYMASTER] or self.game.finished
                    file = discord.File(self.game.generate_image(is_spymaster, reveal_covered=False), filename="codenames.png")
                    await interaction.message.edit(attachments=[file])
                elif action == "enter-clue":
                    await interaction.response.send_modal(self.game.ClueModal(self.game))
                elif action == "rematch":
                    game_setup = GameSetup(self.game.bot)
                    user_ids = list(self.game.roles.values())
                    await game_setup.send_new_user_messages(user_ids, user_name)
                elif action == "end-turn":
                    self.game.add_history(f"{user_name} finished guessing.")
                    await self.game.next_turn()

                # noinspection PyUnresolvedReferences
                await interaction.response.defer()
            except CodenamesException as e:
                # noinspection PyUnresolvedReferences
                await interaction.response.send_message(str(e), ephemeral=True)
            except Exception as e:
                await send_error_message(self.game.bot, e)

            return True

    class ClueModal(Modal, title="Enter your clue"):
        clue = ui.TextInput(label="Clue")
        number = ui.TextInput(label="Number")

        def __init__(self, game):
            super().__init__()
            self.game = game    # type: Game

        async def on_submit(self, interaction: discord.Interaction):
            try:
                # noinspection PyUnresolvedReferences
                await interaction.response.defer()

                user_id = interaction.user.id
                await self.game.give_clue(user_id, self.clue.value, self.number.value)
            except CodenamesException as e:
                # noinspection PyUnresolvedReferences
                await interaction.followup.send_message(str(e), ephemeral=True)
            except Exception as e:
                await send_error_message(self.game.bot, e)
