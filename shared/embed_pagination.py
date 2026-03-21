import discord

from constants import EMBED_DESCRIPTION_MAX_CHARACTERS, EMBED_MAX_CHARACTERS, EMBED_MAX_FIELDS


def paginate_embed_fields(embed: discord.Embed):
    embeds = []
    new_embed = discord.Embed(title=embed.title, color=embed.color)
    embeds.append(new_embed)
    title_length = len(embed.title) + 15  # Add 15 extra characters as wiggle room, to support page numbers into the triple digits
    current_embed_length = title_length

    for field in embed.fields:
        field_length = len(field.name) + len(field.value)
        # Check if there's enough space left for this field in the embed, if not, create a new embed
        if ((current_embed_length + field_length) > EMBED_MAX_CHARACTERS) or \
                (len(new_embed.fields) >= EMBED_MAX_FIELDS):
            new_embed = discord.Embed(title=embed.title, color=embed.color)
            embeds.append(new_embed)
            current_embed_length = title_length

        # Add the field to the new embed
        current_embed_length += field_length
        new_embed.add_field(name=field.name, value=field.value, inline=field.inline)

    # Update each embed's title to indicate their page number
    if len(embeds) > 1:
        for i, new_embed in enumerate(embeds, 1):
            new_embed.title += f" (page {i}/{len(embeds)})"

    return embeds


def paginate_embed_description(embed: discord.Embed) -> list[discord.Embed]:
    embeds = []
    current_embed_description = ""

    for line in embed.description.split("\n"):
        # Check if there's enough space left for this line in the embed, if not, create a new embed with the description that fits
        if (len(current_embed_description) + len(line)) > EMBED_DESCRIPTION_MAX_CHARACTERS:
            embeds.append(discord.Embed(title=embed.title, description=current_embed_description, color=embed.color))
            current_embed_description = ""

        current_embed_description += "\n" + line

    embeds.append(discord.Embed(title=embed.title, description=current_embed_description, color=embed.color))

    # Update each embed's title to indicate their page number
    if len(embeds) > 1:
        for i, new_embed in enumerate(embeds, 1):
            new_embed.title += f" (page {i}/{len(embeds)})"

    return embeds
