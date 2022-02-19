import hikari
import lightbulb


class TagAlreadyExists(Exception):
    """
    Raised when a tag is trying to get created but already exists.
    """


class TagNotFound(Exception):
    """
    Raised when a tag is not found, although most functions just return None.
    """


class RoleHierarchyError(lightbulb.CheckFailure):
    """
    Raised when an action fails due to role hierarchy.
    """


class BotRoleHierarchyError(lightbulb.CheckFailure):
    """
    Raised when an action fails due to the bot's role hierarchy.
    """


class MemberExpectedError(Exception):
    """
    Raised when a command expected a member and received a user instead.
    """
