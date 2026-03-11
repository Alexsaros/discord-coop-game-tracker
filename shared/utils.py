from shared.exceptions import InvalidArgumentException


def parse_boolean(boolean_string):
    boolean_string_lower = boolean_string.lower()
    if boolean_string_lower[:1] in ["y", "t"]:
        return True
    elif boolean_string_lower[:1] in ["n", "f"]:
        return False
    else:
        raise InvalidArgumentException(f"Received invalid argument ({boolean_string}). Must be either \"yes\" or \"no\".")
