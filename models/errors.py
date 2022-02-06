import hikari


class TagAlreadyExists(Exception):
    """
    Raised when a tag is trying to get created but already exists.
    """


class TagNotFound(Exception):
    """
    Raised when a tag is not found, although most functions just return None.
    """


class UserInputError(Exception):
    """
    Triggered when a user entered a wrong value.
    """


class PunishFailed(Exception):
    """
    Raised when punishing the user failed.
    """


class RoleHierarchyError(Exception):
    """
    Raised when an action fails due to role hierarchy.
    """
