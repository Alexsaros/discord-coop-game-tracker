import asyncio
import random

from discord.ext import commands

from shared.logger import log


class CustomHelpCommand(commands.DefaultHelpCommand):

    async def send_bot_help(self, mapping):
        await self.context.message.delete()
        self.width = 1000   # Allows all command descriptions to be displayed
        self.no_category = "Commands"

        # 20% chance to send a spooky message
        chance_roll = random.randint(1, 5)
        if chance_roll == 1:
            spooky_messages = ["Nobody can help you now...", "Help is near... but so is something else.", "It's too late for help now..."]
            spooky_message = random.choice(spooky_messages)
            channel = self.get_destination()
            message = await channel.send(spooky_message)
            log(f"Sent spooky message: {spooky_message}")
            await asyncio.sleep(2.5)
            await message.delete()

        # Send the actual help message
        await super().send_bot_help(mapping)

    def add_indented_commands(self, commands, *, heading, max_size=None):
        if not commands:
            return

        self.paginator.add_line(f"{heading}")

        max_size = max_size or self.get_max_size(commands)

        for command in commands:
            name = command.name
            entry = f"{self.indent * ' '}{name:<{max_size}} {command.short_doc}"
            self.paginator.add_line(entry)

        self.paginator.add_line("")
