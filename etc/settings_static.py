import miru
import hikari

# Static values for the settings extension

mod_settings_strings = {
    "dm_users_on_punish": "DM users after punishment",
    "is_ephemeral": "Send mod commands ephemerally",
}

default_automod_policies = {
    "invites": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
        "excluded_roles": [],
    },
    "spam": {
        "state": "disabled",
        "temp_dur": 15,
        "excluded_channels": [],
        "excluded_roles": [],
    },
    "mass_mentions": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "count": 10,
        "excluded_channels": [],
        "excluded_roles": [],
    },
    "attach_spam": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
        "excluded_roles": [],
    },
    "link_spam": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
        "excluded_roles": [],
    },
    "caps": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
        "excluded_roles": [],
    },
    "bad_words": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
        "excluded_roles": [],
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
    "escalate": {
        "state": "disabled",
        "step1": "disabled",
        "step2": "disabled",
        "step3": "disabled",
    },
}

# Policy state configuration
policy_states = {
    "disabled": {"name": "Disabled", "excludes": []},
    "notice": {"name": "Notice", "excludes": ["spam"]},
    "warn": {"name": "Warn", "excludes": ["spam"]},
    "escalate": {"name": "Escalation", "excludes": ["spam", "escalate"]},
    "timeout": {"name": "Timeout", "excludes": []},
    "kick": {"name": "Kick", "excludes": []},
    "softban": {"name": "Softban", "excludes": []},
    "tempban": {"name": "Tempban", "excludes": []},
    "permaban": {"name": "Ban", "excludes": []},
}

notices = {
    "invites": "posting discord invites",
    "mass_mentions": "mass mentioning users",
    "zalgo": "using zalgo in your messages",
    "attach_spam": "spamming attachments",
    "link_spam": "posting links too fast",
    "caps": "using excessive caps in your message",
    "bad_words": "using bad words in your message",
}

policy_fields = {
    "temp_dur": {"name": "Temporary punishment duration:", "value": "{value} minute(s)", "label": "Duration"},
    "delete": {"name": "Delete offending messages:", "value": "{value}", "label": "Deletion"},
    "count": {"name": "Count:", "value": "{value}", "label": "Count"},
    "words_list": {"name": "Blacklisted Words (Exact):", "value": "||{value}||", "label": "Words (Exact)"},
    "words_list_wildcard": {
        "name": "Blacklisted Words (Wildcard):",
        "value": "||{value}||",
        "label": "Words (Wildcard)",
    },
    "excluded_channels": {"name": "Excluded Channels:", "value": "{value}", "label": "Excluded Channels"},
    "excluded_roles": {"name": "Excluded Roles:", "value": "{value}", "label": "Excluded Roles"},
}

policy_text_inputs = {
    "temp_dur": miru.TextInput(
        label="Temporary Punishment Duration",
        placeholder="Enter a positive integer number as the temporary punishment duration in minute(s)...",
        max_length=6,
        required=True,
    ),
    "count": miru.TextInput(
        label="Count", placeholder="Enter a positive integer number as the count.", max_length=3, required=True
    ),
    "words_list": miru.TextInput(
        label="Blacklisted Words",
        placeholder="Enter a comma-separated list of bad words that will be filtered from chat.",
        required=True,
        style=hikari.TextInputStyle.PARAGRAPH,
    ),
    "words_list_wildcard": miru.TextInput(
        label="Blacklisted Words (Wildcard)",
        placeholder="Enter a comma-separated list of bad words that will be filtered from chat.",
        required=True,
        style=hikari.TextInputStyle.PARAGRAPH,
    ),
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
