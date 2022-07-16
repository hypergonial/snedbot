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


class InteractionTimeOutError(Exception):
    """
    Raised when a user interaction times out.
    """


# Copyright (C) 2022-present HyperGH

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see: https://www.gnu.org/licenses
