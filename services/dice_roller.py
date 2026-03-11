import random
import re

from main import InvalidArgumentException


def roll_dice(username: str, expression: str) -> str:
    if not re.fullmatch(r"[\d+\-*/().d\s]+", expression):
        raise InvalidArgumentException(f"The entered dice rolls contains invalid characters.")

    # Ensure Discord doesn't try to parse the asterisks
    expression = expression.replace("*", "\\*")

    display_text = expression
    eval_expression = expression
    display_offset = 0
    eval_offset = 0

    for match in re.finditer(r"(\d+)d(\d+)", expression):
        amount, sides = map(int, match.groups())
        rolls = [random.randint(1, sides) for _ in range(amount)]

        rolls_text = "+".join(str(roll) for roll in rolls)
        rolls_text = f"`{rolls_text}`"  # Make results of individual dice rolls monospace

        start, end = match.start(), match.end()
        # Replace the dice roll with the results of the dice roll
        display_text = display_text[:start + display_offset] + rolls_text + display_text[end + display_offset:]
        # Keep track of how much the display string shifted in length compared to the original string
        display_offset += len(rolls_text) - (end - start)

        eval_string = str(sum(rolls))
        # Do the same for the eval string
        eval_expression = eval_expression[:start + eval_offset] + eval_string + eval_expression[end + eval_offset:]
        eval_offset += len(eval_string) - (end - start)

    # Remove backslashes and compute the result
    eval_expression = eval_expression.replace("\\", "")
    result = eval(eval_expression)

    message_text = f"{username} rolls: {expression}.\nResult: {display_text} = **{result}**.\n## **{result}**"
    return message_text
