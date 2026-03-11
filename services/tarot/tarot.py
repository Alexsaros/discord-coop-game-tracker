import os
import random

import discord

TAROT_EMBED_COLOR = discord.Color.gold()

TAROT_CARDS = {
    "0": {
        "number": 0,
        "name": "The Fool",
        "meaning_upright": "It’s time for a new adventure, but there is a level of risk. Consider your options carefully, and when you are sure, take that leap of faith.",
        "meaning_reversed": " Beware false promises and naïveté. Don’t lose touch with reality.",
    },
    "1": {
        "number": 1,
        "name": "The Magician",
        "meaning_upright": "It’s time for action - your travel plans, business and creative projects are blessed. You have the energy and wisdom you need to make it happen now. Others see your talent.",
        "meaning_reversed": "False appearances. A scheme or project you’re involved in doesn’t ring true. A further meaning is a creative block, and travel plans being put on hold.",
    },
    "2": {
        "number": 2,
        "name": "The High Priestess",
        "meaning_upright": "Your dreams and your intuition provide the answers you need. This is a psychic card, revealing that truth comes from unconventional sources. You may find a wonderful course, guide or advisor at this time.",
        "meaning_reversed": "You may be let down by an authority figure pro other person you trust; there’s a side to this situation that has been covered up - until now.",
    },
    "3": {
        "number": 3,
        "name": "The Empress",
        "meaning_upright": "Enjoy this productive, joyful time when you’ll have the energy to develop your projects, decorate your home, spend time with children, and give yourself a little luxury. Money flows and love grows under The Empress’s influence.",
        "meaning_reversed": "Household problems, lack of time and money, and even a difficult older woman are the meanings of the Empress reversed. Hold on - things will improve if you keep calm.",
    },
    "4": {
        "number": 4,
        "name": "The Emperor",
        "meaning_upright": "Help, protection and the influence of a powerful individual for whom action speaks louder than words. Tradition is the watchword of The Emperor, so this is a time to play by the rules rather than flout convention.",
        "meaning_reversed": "Disorder; a controlling boss or older relative, poor leadership at work, bullying and upset in relationships. This person may oppose you, but view this as an opportunity to assert your own values.",
    },
    "5": {
        "number": 5,
        "name": "The Hierophant",
        "meaning_upright": "The Hierophant stands for unity. In your everyday life, he shows you committing to your goals so they become reality; you take action rather than daydream. He’s also a symbol of education, asking you to know yourself more deeply and to be open to new wisdom.",
        "meaning_reversed": "Perfectionism, self-criticism, and chaos in communities and at home. Projects become blocked due to miscommunication. If possible, step back and redefine what you alone want, regardless of others.",
    },
    "6": {
        "number": 6,
        "name": "The Lovers",
        "meaning_upright": "There’s amazing potential for lasting love, or reward, but you’ll need to make a mature choice that takes into account long-term rather than short-term benefits. Consider your future rather than old attitudes that don’t serve you.",
        "meaning_reversed": "Choosing the easier option under pressure and in relationships, feeling betrayed or let down by a partner. Don’t sacrifice your needs to keep the peace; put yourself first, even if that means walking away.",
    },
    "7": {
        "number": 7,
        "name": "The Chariot",
        "meaning_upright": "It’s time to take charge and move on. This may be a physical journey, or progress in work, relationships and projects. The Chariot often arrives in a reading after a major decision prompted by cards such as The Lovers, Judgement or The Moon.",
        "meaning_reversed": "Journeys and projects are delayed; a wrong turning. Recheck your plans and pay attention to detail you can fix. There’s arrogance around just now, too.",
    },
    "8": {
        "number": 8,
        "name": "Strength",
        "meaning_upright": "There’s tension around as you will have to keep strong-minded individuals - or your own urges - in check. Hold your space, be patient, and you’ll succeed with grace. An additional meaning is balance masculine and feminine qualities.",
        "meaning_reversed": "Avoiding facing an opponent; hiding from a challenge you could learn from. Your intuition knows not to shy away; it’s time to step up and turn the lion into a pussycat.",
    },
    "9": {
        "number": 9,
        "name": "The Hermit",
        "meaning_upright": "The need to think and heal the past; an opportunity to know yourself more deeply and find the strength and wisdom within. This is a path you choose, and you are alone, not lonely.",
        "meaning_reversed": "Isolation due to stubbornness; a turning away from support through fear. If you’re tired of being alone, reach out a little.",
    },
    "10": {
        "number": 10,
        "name": "Wheel of Fortune",
        "meaning_upright": "A change for the better. Blocks to progress dissolve quickly as events move on, so be open to whatever positive change comes. Look to the future.",
        "meaning_reversed": "The end of a negative cycle of events; you’re almost through the bad times, ready to move on to brighter possibilities.",
    },
    "11": {
        "number": 11,
        "name": "Justice",
        "meaning_upright": "A situation is resolved, ending a period of uncertainty. This card often heralds the end of a legal matter, but in general terms it predicts balance - so harmony is restored - and success, too.",
        "meaning_reversed": "Injustice; a decision goes against you. Keep the faith and seek out people who understand your position; turn away from those who seek to manipulate the situation for their own ends.",
    },
    "12": {
        "number": 12,
        "name": "The Hanged Man",
        "meaning_upright": "Delay. Waiting for change is frustrating, but it does allow you time to see a situation from a different perspective and devise new creative ways forward. An additional meaning is making a sacrifice in order to move on.",
        "meaning_reversed": "Indecision and fantasy; a refusal to be practical and get things done. Procrastination wastes your time.",
    },
    "13": {
        "number": 13,
        "name": "Death",
        "meaning_upright": "Transformation and change. This card doesn’t mean physical death, rather a time of transition, when whatever is not needed for the future must be given up. He brings release from the past, and new beginnings and opportunities.",
        "meaning_reversed": "Hanging onto the past; a refusal to leave the past alone.",
    },
    "14": {
        "number": 14,
        "name": "Temperance",
        "meaning_upright": "Balancing opposites; completing a multitude of tasks at once, which tests your skills and patience. If you can keep every plate spinning, others will see just how resourceful you are. An additional meaning is an opportunity to heal past issues.",
        "meaning_reversed": "Difficult memories; the past dominating the present. Ignoring debts and demands that need attention.",
    },
    "15": {
        "number": 15,
        "name": "The Devil",
        "meaning_upright": "Control issues; being in a relationship or other commitment that enslaves you. This is your perception, borne from obligation, guilt or fear. You can choose to walk away at any time. An additional meaning is struggle with addiction.",
        "meaning_reversed": "Manipulation and entrapment; an influence you find hard to resist, or one that repeats - you leave, return and leave again.",
    },
    "16": {
        "number": 16,
        "name": "The Tower",
        "meaning_upright": "Sudden endings that feel senseless and unnecessary wake you up to the fact that none of us is in control of the universe. This destruction illuminates the hidden tension holding together an aspect of your life; let it go.On a mundane level, The Tower also represents migraine attack.",
        "meaning_reversed": "Overthinking past events and apportioning blame. Don’t ruminate on the past - there is no fault.",
    },
    "17": {
        "number": 17,
        "name": "The Star",
        "meaning_upright": "Guidance, hope and inspiration; a time to nurture your talents and express your feelings. You are on the right path.",
        "meaning_reversed": "Living in a dream world, or a person full of ideas they can’t make happen just now. You may need to revise your expectations - it’s time for a reality-check.",
    },
    "18": {
        "number": 18,
        "name": "The Moon",
        "meaning_upright": "A difficult choice. You may doubt what’s on offer and feel you can’t see a clear picture. Take your time to listen to your inner voice; you don’t need to give in to pressure to make a decision. Intuition rather than reason will light the way.",
        "meaning_reversed": "Avoiding emotional issues; feeling disillusioned and unsafe. It may be risky, but it’s better to take a chance rather than do nothing.",
    },
    "19": {
        "number": 19,
        "name": "The Sun",
        "meaning_upright": "Happiness, protection and joy; a successful phase. A carefree time when old worries disappear. A further meaning is good health and renewed energy.",
        "meaning_reversed": "Frustration due to delayed plans, and holidays and projects may go on hold for a while, but don’t be downhearted - everything will get quickly back on track.",
    },
    "20": {
        "number": 20,
        "name": "Judgement",
        "meaning_upright": "Reviewing the past; deciding if it’s worth reconsidering a decision or situation. You’re in the process of judging yourself, too, musing on your past actions and relationships.",
        "meaning_reversed": "Guilt and worry may keep you tethered to the past. While it’s important to look back before you move on, there’s only so much soul-searching you, or someone close to you, can do.",
    },
    "21": {
        "number": 21,
        "name": "The World",
        "meaning_upright": "A successful conclusion before the beginning of a bright new phase; the world is opening up to you. You’re also rewarded with love, new opportunities and even gifts. A further meaning is peace and optimism.",
        "meaning_reversed": "An opportunity denied; you may feel your options are limited just now, but be patient - your time to travel and encounter exciting new opportunities will come.",
    },
}


def create_random_tarot_embed(username: str) -> tuple[discord.Embed, discord.File]:
    # Draw a random card
    card_key = random.choice(list(TAROT_CARDS.keys()))
    card_dict = TAROT_CARDS[card_key]
    card_name = card_dict["name"]
    is_reversed = random.choice([True, False])
    card_position = "(Reversed)" if is_reversed else "(Upright)"

    # Get the image and create a Discord File object
    image_filename = f"{card_key}-{card_name.lower().replace(' ', '-')}"
    image_filename += "-reversed.jpg" if is_reversed else ".jpg"
    image_path = os.path.join(os.path.dirname(__file__), "cards", image_filename)
    file = discord.File(image_path, filename=image_filename)

    # Create the embed
    title = f"{username} pulled tarot card: {card_name} {card_position}"
    interpretation = card_dict["meaning_reversed"] if is_reversed else card_dict["meaning_upright"]
    tarot_embed = discord.Embed(
        title=title,
        description=interpretation,
        color=TAROT_EMBED_COLOR
    )
    return tarot_embed, file

