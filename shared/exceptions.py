
class BotException(Exception):

    message = ""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class GameNotFoundException(BotException):
    pass


class UserNotFoundException(BotException):
    pass


class NoAccessException(BotException):
    pass


class InvalidArgumentException(BotException):
    pass


class InvalidChannelException(BotException):
    pass


class ApiException(Exception):
    pass
