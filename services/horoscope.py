import datetime
import random

import discord

HOROSCOPE_EMBED_COLOR = discord.Color.magenta()

THINGS = ["destiny", "puppies", "the weather", "the supernatural", "liveliness", "death", "wealth", "unreasonable demands",
          "adventure", "bad luck", "good luck", "change", "disaster", "challenges", "unexpected news", "opportunities", "strong emotions",
          "punishment", "short breaks", "taxes", "happiness", "new relationships", "an unexpected gift", "secrets",
          "destiny", "revelations", "the unknown", "fortune", "a turning point", "nature", "life", "personal growth", "a chance encounter"]
PREDICTIONS_PRE = ["must be cautious of", "would do well to avoid", "can expect", "might encounter", "would benefit from being accepting of",
                   "must not be receptive to", "can not avoid", "will be delighted by", "will be doomed by", "might be taken aback by",
                   "will experience", "could be pleasantly surprised by", "may find yourself dealing with", "should keep an eye on"]
WHERE = ["nearby", "close to you", "at your approximate location", "in your neighbourhood", "in your surroundings", "within reach",
         "under your bed", "where you least expect it", "somewhere close", "just around the corner", "at a place you hold dear",
         "in nature", "all around you", "on your daily commute", "on your next journey", "in a hidden location", "in crowded areas",
         "on a quiet street", "in your dreams", "amidst chaos", "in technology", "out there"]
PREDICTIONS_POST = ["will find you", "will help you out", "might cause problems", "could appear", "will change things up",
                    "could distract you from your goal", "will be absent", "might offer a unique chance", "may disappear"]
TIMES = ["before you know it", "when Mercury is in retrograde", "when you least expect it", "at an inopportune moment",
         "in your hour of need", "at a moment of peace", "during unusual events", "at mealtime", "while you're out", "while you're relaxing",
         "at just the right moment", "in the near future", "when the time is right", "when the opportunity arises"]
ADVICE = ["my advice is to", "you would do best not to", "your future might change if you", "go forth and", "consider to",
          "be sure to", "it might be time to", "you'll find peace if you would", "try to", "do not hesitate to", "perhaps you should"]
ACTIONS = ["go out and explore", "stay indoors", "take it easy", "be proactive", "reconsider things", "take advantage of new opportunities",
           "destroy your enemies", "chase your dreams", "take up a new hobby", "prepare for the worst", "start something new", "trust your instincts"]
CONNECTORS = ["moreover", "additionally", "on top of that", "finally", "furthermore", "on another note"]


def create_horoscope_embed(username: str) -> discord.Embed:
    # Create a seed based on the user's name and today's date
    seed = hash(f"{username}{datetime.date.today()}")
    # Use the seed for random number generation
    rng = random.Random(seed)

    sentence1 = f"You {rng.choice(PREDICTIONS_PRE)} {rng.choice(THINGS)} {rng.choice(WHERE)}."
    sentence2 = f"{rng.choice(CONNECTORS).capitalize()}, {rng.choice(THINGS)} {rng.choice(PREDICTIONS_POST)} {rng.choice(TIMES)}."
    sentence3 = f"{rng.choice(ADVICE).capitalize()} {rng.choice(ACTIONS)}."

    # Create the horoscope embed
    title = f"{username}'s horoscope :sparkles:"
    horoscope_text = f"{sentence1} {sentence2} {sentence3}"
    horoscope_embed = discord.Embed(
        title=title,
        description=horoscope_text,
        color=HOROSCOPE_EMBED_COLOR
    )
    return horoscope_embed

