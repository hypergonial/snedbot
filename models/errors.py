import hikari


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


class PermissionsMissing(Exception):
    """
    Raised when a permission check performed on certain actions failed.
    """

    def __init__(self, missing_perms: hikari.Permissions, *args: object) -> None:
        super().__init__(*args)
        self.missing_perms: hikari.Permissions = missing_perms


class BotPermissionsMissing(PermissionsMissing):
    """
    Raised when a permission check performed on certain actions failed
    due to the bot lacking permissions.
    """
