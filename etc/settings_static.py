import hikari
import miru

from models.mod_actions import ModerationFlags

# Static values for the settings extension

mod_flags_strings = {
    ModerationFlags.DM_USERS_ON_PUNISH: "DM users after punishment",
    ModerationFlags.IS_EPHEMERAL: "Send mod commands ephemerally",
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
    "perspective": {
        "state": "disabled",
        "temp_dur": 15,
        "delete": True,
        "excluded_channels": [],
        "excluded_roles": [],
        "persp_bounds": {"TOXICITY": 0.90, "SEVERE_TOXICITY": 0.90, "THREAT": 0.90, "PROFANITY": 0.90, "INSULT": 0.90},
    },
    "escalate": {
        "state": "disabled",
    },
}

# Policy state configuration
policy_states = {
    "disabled": {"name": "Disabled", "excludes": [], "description": "Disable this policy.", "emoji": "🚫"},
    "flag": {"name": "Flag", "excludes": ["spam"], "description": "Log message to 'Auto-Mod Flagging'.", "emoji": "🚩"},
    "notice": {
        "name": "Notice",
        "excludes": ["spam"],
        "description": "Flag the message and prompt the user to stop.",
        "emoji": "💬",
    },
    "warn": {
        "name": "Warn",
        "excludes": ["spam"],
        "description": "Warn user. Increases warn counter. Logs under 'Warns'.",
        "emoji": "⚠️",
    },
    "escalate": {
        "name": "Escalation",
        "excludes": ["spam", "escalate"],
        "description": "Execute the policy defined in 'Escalation'.",
        "emoji": "⏫",
    },
    "timeout": {
        "name": "Timeout",
        "excludes": [],
        "description": "Time out the user for the specified temporary duration.",
        "emoji": "🔇",
    },
    "kick": {"name": "Kick", "excludes": [], "description": "Kick the user.", "emoji": "🚪"},
    "softban": {
        "name": "Softban",
        "excludes": [],
        "description": "Ban and unban the user, deleting their messages.",
        "emoji": "🔨",
    },
    "tempban": {"name": "Tempban", "excludes": [], "description": "Temporarily ban the user.", "emoji": "🔨"},
    "permaban": {"name": "Permaban", "excludes": [], "description": "Permanently ban the user.", "emoji": "🔨"},
}

notices = {
    "invites": "posting discord invites",
    "mass_mentions": "mass mentioning users",
    "zalgo": "using zalgo in your messages",
    "attach_spam": "spamming attachments",
    "link_spam": "posting links too fast",
    "caps": "using excessive caps in your message",
    "bad_words": "using bad words in your message",
    "perspective": "using offensive language in your message",
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
    "persp_bounds": {"name": "Perspective Bounds:", "value": "{value}", "label": "Set Bounds"},
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
        "name": "Escalation",
        "description": """This event is triggered when any other policy's punishment is set to escalation, and escalates measures, culminating in the punishment specified below. 
        
**The flow is the following:**
**1.** The user is given a notice
**2.** If ignored, the user is warned
**3.** If also ignored, the action below is executed on the user

Other parameters such as the duration of temporary punishment (if temporary), the deletion of message, excluded roles/channels, etc.. **are inherited from the original policy.**\n""",
    },
    "perspective": {
        "name": "Perspective",
        "description": """Uses advanced machine learning algorithms to detect and filter out potentially toxic messages. Learn more about Perspective [here](https://www.perspectiveapi.com/).
        
Below you can set the percentages after which action will be taken based on the Perspective action-types. It is recommended to set at least a `0.85` (85%) confidence rate or higher for all values.
​
Staff members are encouraged to play around with the percentages with only the `Flag` state selected, to test the sensitiveness of the system. Perspective is not a replacement for human moderators, and should not be treated as such.
​
Currently supported languages: **English**, **German**, **Italian**, **Portuguese**, **Russian**""",
    },
}

settings_help = {
    "policies": {
        "perspective": hikari.Embed(
            title="Help for: Perspective",
            color=0x009DFF,
            description="""[Perspective](https://www.perspectiveapi.com/) is an API that uses machine learning to identify toxic comments.
​
**How does it work?**
After enabling the policy, you can set different bounds for the different attributes (see below), these specify the percentage of confidence above which the bot should take action. If you would like to **disable an attribute**, simply set it to `1.0`, as no the probability will ever hit 100%.
​
**Available Attributes:**
`Toxicity` - A rude, disrespectful, or unreasonable comment that is likely to make people leave a discussion.
`Severe Toxicity` - A very hateful, aggressive, disrespectful comment or otherwise very likely to make a user leave a discussion or give up on sharing their perspective. This attribute is much less sensitive to more mild forms of toxicity, such as comments that include positive uses of curse words.
`Insult` - Insulting, inflammatory, or negative comment towards a person or a group of people.
`Profanity` - Swear words, curse words, or other obscene or profane language.
`Threat` - Describes an intention to inflict pain, injury, or violence against an individual or group.""",
        )
    }
}

log_event_strings = {
    "ban": "Ban",
    "kick": "Kick",
    "timeout": "Timeout",
    "message_delete": "Message Deletion",
    "message_delete_mod": "Message Deletion by Mod",
    "message_edit": "Message Edits",
    "bulk_delete": "Message Purging",
    "flags": "Auto-Mod Flagging",
    "roles": "Roles",
    "channels": "Channels",
    "member_join": "Member join",
    "member_leave": "Member leave",
    "nickname": "Nickname change",
    "guild_settings": "Server settings",
    "warn": "Warnings",
}

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
