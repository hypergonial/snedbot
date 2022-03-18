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


class UserBlacklistedError(Exception):
    """
    Raised when a user who is blacklisted from using the application tries to use it.
    """


class DMFailedError(Exception):
    """
    Raised when DMing a user fails while executing a moderation command.
    """


class DatabaseStateConflictError(Exception):
    """
    Raised when the database's state conflicts with the operation requested to be carried out.
    """
