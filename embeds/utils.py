from sqlalchemy.orm import joinedload

from database.db import db_session_scope
from database.models import Game, GameUserData, ServerMember, ReleaseState

EMOJIS = {
    "owned": ":video_game:",
    "not_owned": ":money_with_wings:",
    "1players": ":person_standing:",
    "2players": ":people_holding_hands:",
    "3players": ":family_man_girl_boy:",
    "4players": ":family_mmgb:",
    "free": ":free:",
    "local": ":satellite:",
    "experienced": ":brain:",
    "new": ":new:",
    "question": ":question:",
}


# Thresholds for ratings on whether someone is okay with missing out on playing a game or not (inclusive)
ALWAYS_WANT_TO_PLAY_RATING_THRESHOLD = 8    # or higher
NEVER_WANT_TO_PLAY_RATING_THRESHOLD = 3     # or lower


def sort_games_by_score(games: list[Game], member_count: int) -> list[tuple[Game, int]]:
    game_scores = []

    for game in games:
        # Count the score for this game
        with db_session_scope() as db_session:
            game_user_data_list = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == game.server_id)
                    .filter(GameUserData.game_id == game.id)
                    .all()
            )   # type: list[GameUserData]

            if not game.finished:
                votes = [data.vote for data in game_user_data_list if data.vote is not None]
            else:
                votes = [data.enjoyment_score for data in game_user_data_list if data.enjoyment_score is not None]

        total_score = sum(votes)
        # Use a score of 5 for the non-voters
        non_voter_count = member_count - len(votes)
        total_score += non_voter_count * 5

        game_scores.append((game, total_score))

    return sorted(game_scores, key=lambda x: x[1], reverse=True)


def filter_games_by_selected_users(games: list[Game], selected_user_ids: list[int], excluded_user_ids: list[int]) -> list[Game]:
    filtered_games = []

    for game in games:
        # Only show games that can be played with the amount of selected players
        if game.player_count is not None and \
                len(selected_user_ids) > game.player_count and \
                len(selected_user_ids) % game.player_count != 0:
            # This game supports less players than desired, and can not be split evenly into multiple parties
            continue

        with db_session_scope() as db_session:
            game_user_data_list = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == game.server_id)
                    .filter(GameUserData.game_id == game.id)
                    .filter(GameUserData.vote.isnot(None))
                    .all()
            )  # type: list[GameUserData]

            skip_game = False

            # Check whether to skip a game based on someone (not) wanting to play it
            for user_data in game_user_data_list:
                # Skip this game if a selected user does not want to play it
                if user_data.user_id in selected_user_ids and user_data.vote <= NEVER_WANT_TO_PLAY_RATING_THRESHOLD:
                    skip_game = True
                    break
                # Skip this game if an excluded user really wants to play it
                if user_data.user_id in excluded_user_ids and user_data.vote >= ALWAYS_WANT_TO_PLAY_RATING_THRESHOLD:
                    skip_game = True
                    break

            if skip_game:
                continue

            filtered_games.append(game)

    return filtered_games


def sort_games_by_score_and_selected_users(games: list[Game], selected_user_ids: list[int], excluded_user_ids: list[int]) -> list[tuple[Game, int]]:
    game_scores = []
    total_member_count = len(selected_user_ids) + len(excluded_user_ids)
    # A user's vote who is excluded weighs more heavily
    excluded_user_vote_weight = total_member_count

    for game in games:
        with db_session_scope() as db_session:
            game_user_data_votes = (
                db_session.query(GameUserData)
                    .filter(GameUserData.server_id == game.server_id)
                    .filter(GameUserData.game_id == game.id)
                    .filter(GameUserData.vote.isnot(None))
                    .all()
            )  # type: list[GameUserData]

        voter_user_ids = set(user_data.user_id for user_data in game_user_data_votes)
        non_voter_user_ids = set(selected_user_ids + excluded_user_ids) - voter_user_ids

        # Count the score for this game
        total_score = 0
        for data in game_user_data_votes:
            if data.user_id in selected_user_ids:
                total_score += data.vote
            elif data.user_id in excluded_user_ids:
                total_score -= data.vote * excluded_user_vote_weight

        # Use a score of 5 for the non-voters
        for user_id in non_voter_user_ids:
            if user_id in selected_user_ids:
                total_score += 5
            elif user_id in excluded_user_ids:
                total_score -= 5 * excluded_user_vote_weight

        game_scores.append((game, total_score))

    return sorted(game_scores, key=lambda x: x[1], reverse=True)


def get_users_aliases_string(server_id: int, user_ids: list[int]) -> str:
    with db_session_scope() as db_session:
        # Get each user's alias, falling back to their global name if not set
        users_text = ""
        members = (
            db_session.query(ServerMember)
                .options(joinedload(ServerMember.user))     # Also preemptively retrieve User data
                .filter(ServerMember.server_id == server_id)
                .filter(ServerMember.user_id.in_(user_ids))
                .all()
        )   # type: list[ServerMember]

        user_names = []
        user_aliases = []
        for member in members:
            if member.alias is not None:
                user_aliases.append(member.alias)
            else:
                user_names.append(member.user.global_name)

        users_text += " ".join(user_aliases)
        users_text += ", ".join(user_names)
        return users_text


def generate_price_text(game: Game) -> str:
    if game is None:
        return ""

    release_state_text = ""
    if game.release_state == ReleaseState.UNRELEASED:
        release_state_text = "*coming soon*"
    elif game.release_state == ReleaseState.EARLY_ACCESS:
        release_state_text = "*early access*"

    price_text = ""
    if game.price_original is not None and game.price_current is not None:
        price_original = game.price_original
        price_current = game.price_current

        if price_original == 0:
            price_text = EMOJIS["free"]
        else:
            price_text = f"€{price_original:.2f}"
            # Check if the game has a discount
            if price_current != price_original:
                if price_current == 0:
                    # The game is currently free
                    price_text = f"~~{price_text}~~ **Currently free**"
                else:
                    discount_percent = int(((price_original - price_current) / price_original) * 100)
                    price_text = f"~~{price_text}~~ **€{price_current:.2f}** (-{discount_percent}%)"

    final_text = " ".join([release_state_text, price_text]).strip()
    final_text = final_text if final_text else "unknown"
    return final_text


def get_game_embed_field(game: Game):
    """
    Gets the details of the given game from the dataset to be displayed in an embed field.
    Returns a dictionary with keys "name", "value", and "inline", as expected by Discord's embed field.
    """
    description = ""

    price_text = generate_price_text(game)
    if price_text != "":
        # If we have the Steam game ID, add a hyperlink on the game's price
        if game.steam_id:
            link = f"https://store.steampowered.com/app/{game.steam_id}"
            price_text = f"[{price_text}]({link})"

        description += f"\n> Price: {price_text}"

    with db_session_scope() as db_session:
        game_user_data_list = (
            db_session.query(GameUserData)
                .filter(GameUserData.server_id == game.server_id)
                .filter(GameUserData.game_id == game.id)
                .all()
        )   # type: list[GameUserData]

    voted_user_ids = [data.user_id for data in game_user_data_list if data.vote is not None]
    if voted_user_ids:
        description += "\n> Voted: "
        voters_text = get_users_aliases_string(game.server_id, voted_user_ids)
        description += voters_text

    if game.player_count is not None:
        player_count = min(4, game.player_count)
        player_count_text = EMOJIS[f"{player_count}players"]
        description += f"\n> Players: {player_count_text}"

    # Do not display who owns a game if the game is free, as you can't buy a free game
    owned_user_data_list = [data for data in game_user_data_list if data.owned is not None]
    if (owned_user_data_list or game.local) and game.price_original != 0:
        description += "\n> Owned: "

        if owned_user_data_list:
            owned_count = sum(1 for data in owned_user_data_list if data.owned)
            description += EMOJIS["owned"] * owned_count
            description += EMOJIS["not_owned"] * (len(owned_user_data_list) - owned_count)

        if game.local:
            description += "(" + EMOJIS["local"] + ")"

    played_before_user_data_list = [data for data in game_user_data_list if data.played_before is not None]
    if played_before_user_data_list:
        description += "\n> Experience: "
        played_before_count = sum(1 for data in played_before_user_data_list if data.played_before)
        description += EMOJIS["experienced"] * played_before_count
        description += EMOJIS["new"] * (len(played_before_user_data_list) - played_before_count)

    notes = game.notes
    if len(notes) > 0:
        description += "\n> " + "\n> ".join(notes)

    description = description.strip()

    embed_field_info = {
        "name": f"{game.id} - {game.name}",
        "value": description,
        "inline": False,
    }
    return embed_field_info


def get_current_page_from_message_title(embed_title: str) -> int:
    if "(page " not in embed_title:
        return 1
    page_info = embed_title.split("page ")[-1].rstrip(")")
    current_page = int(page_info.split("/")[0])
    return max(current_page, 1)


def get_total_pages_from_message_title(embed_title: str) -> int:
    if "(page " not in embed_title:
        return 1
    page_info = embed_title.split("page ")[-1].rstrip(")")
    total_pages = int(page_info.split("/")[-1])
    return total_pages
