class TagAlreadyExists(Exception):
    """
    Raised when a tag is trying to get created but already exists.
    """

    pass


class TagNotFound(Exception):
    """
    Raised when a tag is not found, although most functions just return None.
    """

    pass


class UserInputError(Exception):
    """
    Triggered when a user entered a wrong value.
    """

    pass


class PunishFailed(Exception):
    """
    Raised when punishing the user failed.
    """
