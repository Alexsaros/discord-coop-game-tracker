import asyncio
import io
import os
import random
from typing import Optional

import discord
from discord.ext.commands import Bot
from discord.ui import View, Button
from PIL import Image

from apis.discord import get_discord_user


COOPER_ID = -1

CARDS = ["mouse", "elephant", "wolf", "cat"]

BEATS = {
    "mouse": ["elephant"],
    "elephant": ["wolf", "cat"],
    "wolf": ["cat"],
    "cat": ["mouse"]
}

CARD_EMOJIS = {
    "mouse": "🐭",
    "elephant": "🐘",
    "wolf": "🐺",
    "cat": "🐱"
}


CARD_W, CARD_H = 200, 256

TOP_Y = 50
BOTTOM_Y = 350

START_X = 100
GAP = 220  # distance between start of cards

BG_SIZE = (START_X * 2 + CARD_W + GAP * 3, BOTTOM_Y + CARD_H + TOP_Y)


def load_card(path):
    return Image.open(path).convert("RGBA").resize((CARD_W, CARD_H))


CRITTERS_DIR = os.path.dirname(os.path.abspath(__file__))

CARD_IMAGES = {
    card: load_card(os.path.join(CRITTERS_DIR, f"resources/{card}.webp"))
    for card in CARDS
}

BACK_IMAGE = load_card(os.path.join(CRITTERS_DIR, "resources/back.webp"))

STAR_IMAGE = Image.open(
    os.path.join(CRITTERS_DIR, "resources/star.png")
).convert("RGBA").resize((80, 80))


BACKGROUND = Image.open(
    os.path.join(CRITTERS_DIR, "resources/background.png")
).convert("RGBA").resize(BG_SIZE)


def get_winner(a, b):
    if b in BEATS[a]:
        return 1
    if a in BEATS[b]:
        return -1
    return 0


class CrittersGame:
    def __init__(self, bot: Bot, user1: discord.User, user2: Optional[discord.User]):
        self.bot = bot
        user_id1 = user1.id
        user_id2 = user2.id if user2 is not None else COOPER_ID
        self.players = [user_id1, user_id2]

        self.user_map = {
            user_id1: user1,
            user_id2: user2
        }

        self.hands = {
            user_id1: CARDS.copy(),
            user_id2: CARDS.copy()
        }

        self.choices = {}  # type: dict[int, str]
        self.scores = {user_id1: 0, user_id2: 0}
        self.round = 1
        self.history = []  # list of (card1, card2)

        self.messages = {}  # type: dict[int, discord.Message]

        self.rematch_started = False

        if user_id2 == COOPER_ID:
            self.ai_play()

    def play_card(self, user_id: int, card: str):
        if user_id in self.choices:
            return False

        self.choices[user_id] = card
        self.hands[user_id].remove(card)
        self.hands[user_id].append(random.choice(CARDS))
        return True

    def ai_play(self):
        if COOPER_ID in self.choices:
            return

        card = ai_choose_card(self)

        self.choices[COOPER_ID] = card
        self.hands[COOPER_ID].remove(card)
        self.hands[COOPER_ID].append(random.choice(CARDS))

    def resolve_round(self):
        p1, p2 = self.players
        c1 = self.choices[p1]
        c2 = self.choices[p2]

        result = get_winner(c1, c2)
        if result == 1:
            self.scores[p1] += 1
        elif result == -1:
            self.scores[p2] += 1

        self.round += 1
        self.history.append((c1, c2))
        self.choices = {}

        if p2 == COOPER_ID:
            self.ai_play()

    def is_round_ready(self):
        return len(self.choices) == 2

    def is_finished(self):
        return self.round > 4


class CrittersView(View):
    def __init__(self, game: CrittersGame, user_id: int):
        super().__init__(timeout=None)
        self.game = game
        self.user_id = user_id

        self.build_buttons()

    def build_buttons(self):
        self.clear_items()

        hand = self.game.hands[self.user_id]
        already_played = self.user_id in self.game.choices

        game_over = self.game.is_finished()

        for card in hand:
            btn = Button(
                label=None,
                emoji=CARD_EMOJIS[card],
                disabled=already_played or game_over
            )

            def make_callback(card):
                async def callback(interaction):
                    if interaction.user.id != self.user_id:
                        return

                    await interaction.response.defer()

                    if self.game.is_finished():
                        return

                    if not self.game.play_card(self.user_id, card):
                        return

                    await self.update_all()

                return callback

            btn.callback = make_callback(card)
            self.add_item(btn)

        if self.game.is_finished():
            btn = Button(
                label="Rematch",
                style=discord.ButtonStyle.green,
                disabled=self.game.rematch_started
            )

            async def rematch_callback(interaction):
                if interaction.user.id not in self.game.players:
                    return

                if self.game.rematch_started:
                    return

                self.game.rematch_started = True

                await interaction.response.defer()

                await self.update_all()

                p1 = interaction.user.id
                p2 = [p for p in self.game.players if p != p1][0]

                await start_critters_game(self.game.bot, p1, p2)

            btn.callback = rematch_callback
            self.add_item(btn)

    async def update_all(self):
        if self.game.is_round_ready():
            self.game.resolve_round()

        tasks = []

        for user_id in self.game.players:
            if user_id == COOPER_ID:
                continue
            msg = self.game.messages[user_id]
            view = CrittersView(self.game, user_id)

            tasks.append(self.update_single(msg, view, user_id))

        await asyncio.gather(*tasks)

    async def update_single(self, msg, view, user_id):
        file = await render_game(self.game, user_id)

        await msg.edit(
            content=get_status_text(self.game, user_id),
            attachments=[file],
            view=view
        )


def ai_choose_card(game: CrittersGame):
    hand = game.hands[COOPER_ID]

    return random.choice(hand)


def get_status_text(game: CrittersGame, user_id: int):
    opponent_id = [p for p in game.players if p != user_id][0]
    opponent = game.user_map[opponent_id]
    opponent_name = opponent.global_name if opponent is not None else "Cooper"

    if game.is_finished():
        my_score = game.scores[user_id]
        opp_score = game.scores[opponent_id]

        if my_score > opp_score:
            result = "You won!"
        elif my_score < opp_score:
            result = "You lost!"
        else:
            result = "It's a draw!"

        return f"Game over vs {opponent_name} - {result} ({my_score}-{opp_score})"

    return f"Round {game.round} vs {opponent_name}"


def get_positions():
    return [
        (START_X + i * GAP, TOP_Y) for i in range(4)
    ], [
        (START_X + i * GAP, BOTTOM_Y) for i in range(4)
    ]


def paste_star(base, img, pos, is_top):
    x, y = pos

    cx = x + (CARD_W - img.width) // 2

    star_offset = 11

    if is_top:
        # bottom edge of top card
        cy = y + CARD_H - img.height // 2 - star_offset
    else:
        # top edge of bottom card
        cy = y - img.height // 2 + star_offset

    base.paste(img, (cx, cy), img)


async def render_game(game: CrittersGame, user_id: int) -> discord.File:
    base = BACKGROUND.copy()

    p1, p2 = game.players
    opponent_id = p2 if user_id == p1 else p1

    top_positions, bottom_positions = get_positions()

    # Draw previous rounds
    for i, (c1, c2) in enumerate(game.history):
        my_card = c1 if user_id == p1 else c2
        opp_card = c2 if user_id == p1 else c1

        base.paste(CARD_IMAGES[opp_card], top_positions[i], CARD_IMAGES[opp_card])
        base.paste(CARD_IMAGES[my_card], bottom_positions[i], CARD_IMAGES[my_card])

        result = get_winner(my_card, opp_card)
        if result == 1:
            paste_star(base, STAR_IMAGE, bottom_positions[i], is_top=False)
        elif result == -1:
            paste_star(base, STAR_IMAGE, top_positions[i], is_top=True)

    # Draw current round
    if game.round <= 4:
        i = game.round - 1

        my_choice = game.choices.get(user_id)
        opp_choice = game.choices.get(opponent_id)

        if opp_choice:
            if my_choice:
                img = CARD_IMAGES[opp_choice]
            else:
                img = BACK_IMAGE
            base.paste(img, top_positions[i], img)

        if my_choice:
            base.paste(CARD_IMAGES[my_choice], bottom_positions[i], CARD_IMAGES[my_choice])

    buffer = io.BytesIO()
    base.save(buffer, format="PNG")
    buffer.seek(0)

    return discord.File(buffer, filename="game.png")


async def start_critters_game(bot: Bot, user_id: int, opponent_user_id: Optional[int]):
    user1 = await get_discord_user(bot, user_id)
    user2 = None if opponent_user_id in [None, COOPER_ID] else await get_discord_user(bot, opponent_user_id)

    game = CrittersGame(bot, user1, user2)

    for user_id in game.players:
        if user_id == COOPER_ID:
            continue

        discord_user = await get_discord_user(bot, user_id)
        dm = await discord_user.create_dm()

        view = CrittersView(game, user_id)
        file = await render_game(game, user_id)

        if user_id == game.players[0]:
            opponent_name = user2.global_name if user2 is not None else "Cooper"
            text = f"You have challenged {opponent_name} to a Critters battle!"
        else:
            text = f"{user1.global_name} has challenged you to a Critters battle!"

        file_info = discord.File(
            os.path.join(CRITTERS_DIR, "resources/critters_info.webp"),
            filename="info.webp"
        )

        await dm.send(
            content="Critters rules",
            file=file_info
        )

        msg = await dm.send(
            content=text,
            file=file,
            view=view
        )

        game.messages[user_id] = msg
