# Static values for the settings extension

mod_settings_strings = {
    "dm_users_on_punish": "DM users after punishment",
    "clean_up_mod_commands": "Clean up mod commands",
}

default_automod_policies = {
    "invites": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
    },
    "spam": {"state": "disabled", "temp_dur": 15, "excluded_channels": []},
    "mass_mentions": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "count": 10,
        "excluded_channels": [],
    },
    "zalgo": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
    },
    "attach_spam": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
    },
    "link_spam": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
    },
    "caps": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
    },
    "bad_words": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
        "words_list": [
            "motherfucker",
            "cock",
            "cockfucker",
            "anal",
            "cum",
            "anus",
            "porn",
            "pornography",
            "slut",
            "whore",
        ],
        "words_list_wildcard": [
            "blowjob",
            "boner",
            "dildo",
            "faggot",
            "dick",
            "whore",
            "pussy",
            "nigg",
            "cunt",
            "cnut",
            "d1ck",
        ],
    },
    "escalate": {"state": "disabled"},
}

# Policy state configuration
policy_states = {
    "disabled": {"name": "Disabled", "excludes": []},
    "notice": {"name": "Notice", "excludes": ["spam"]},
    "warn": {"name": "Warn", "excludes": ["spam"]},
    "escalate": {"name": "Smart", "excludes": ["spam", "escalate"]},
    "timeout": {"name": "Timeout", "excludes": []},
    "kick": {"name": "Kick", "excludes": []},
    "softban": {"name": "Softban", "excludes": []},
    "tempban": {"name": "Tempban", "excludes": []},
    "permaban": {"name": "Ban", "excludes": []},
}

# Strings for the automod config menu
policy_strings = {
    "invites": {
        "name": "Invites",
        "description": "This event is triggered when a Discord invite is sent in chat.",
    },
    "spam": {
        "name": "Spam",
        "description": "This event is triggered a user sends multiple messages in quick succession.",
    },
    "mass_mentions": {
        "name": "Mass Mentions",
        "description": "This event is triggered when a pre-determined number of mentions is sent in a single message. This does not include mentions of self or bots.",
    },
    "zalgo": {
        "name": "Zalgo",
        "description": "This event is triggered when the bot detects zalgo text in a message.",
    },
    "attach_spam": {
        "name": "Attachment spam",
        "description": "This event is triggered when multiple messages containing attachments are sent in quick succession (e.g. images) by the same user..",
    },
    "link_spam": {
        "name": "Link spam",
        "description": "This event is triggered when multiple messages containing links are sent in quick succession by the same user.",
    },
    "caps": {
        "name": "Caps",
        "description": "This event is triggered when a message includes 80% capitalized characters and is over a certain length.",
    },
    "bad_words": {
        "name": "Bad words",
        "description": "This event is triggered when a message includes any of the bad words configured below.",
    },
    "escalate": {
        "name": "Smart",
        "description": "This event is triggered when any other event's punishment is set to smart, when the bot deemes that warning the user is not enough. Other parameters such as the duration of temporary punishment (if temporary), the deletion of message etc.. are inherited from the original event.",
    },
}

log_event_strings = {
    "ban": "Ban",
    "kick": "Kick",
    "timeout": "Timeout",
    "message_delete": "Message Deletion",
    "message_delete_mod": "Message Deletion by Mod",
    "message_edit": "Message Edits",
    "bulk_delete": "Message Purging",
    "invites": "Invites",
    "roles": "Roles",
    "channels": "Channels",
    "member_join": "Member join",
    "member_leave": "Member leave",
    "nickname": "Nickname change",
    "guild_settings": "Server settings",
    "warn": "Warnings",
}
