-- Creation of all tables necessary for the bot to function

CREATE TABLE IF NOT EXISTS schema_info
(
    schema_version integer NOT NULL,
    PRIMARY KEY (schema_version)
);


-- Insert schema version into schema_info table if not already present
DO
$do$
DECLARE _schema_version integer;
BEGIN
    SELECT 3 INTO _schema_version; -- The current schema version, change this when creating new migrations

	IF NOT EXISTS (SELECT schema_version FROM schema_info) THEN
		INSERT INTO schema_info (schema_version) 
		VALUES (_schema_version); 
	END IF;
END
$do$;

CREATE TABLE IF NOT EXISTS global_config
(
    guild_id bigint NOT NULL,
    prefix text[],
    PRIMARY KEY (guild_id)
);

CREATE TABLE IF NOT EXISTS users
(
    user_id bigint NOT NULL,
    guild_id bigint NOT NULL,
    flags json,
    warns integer NOT NULL DEFAULT 0,
    notes text[],
    PRIMARY KEY (user_id, guild_id),
    FOREIGN KEY (guild_id)
        REFERENCES global_config (guild_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS preferences
(
    user_id bigint NOT NULL,
    timezone text NOT NULL DEFAULT 'UTC',
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS blacklist
(
    user_id bigint NOT NULL,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS mod_config
(
    guild_id bigint NOT NULL,
    dm_users_on_punish bool NOT NULL DEFAULT true,
    is_ephemeral bool NOT NULL DEFAULT false,
    automod_policies json NOT NULL DEFAULT '{}',
    PRIMARY KEY (guild_id),
    FOREIGN KEY (guild_id)
        REFERENCES global_config (guild_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports
(
    guild_id bigint NOT NULL,
    is_enabled bool NOT NULL DEFAULT false,
    channel_id bigint,
    pinged_role_ids bigint[] DEFAULT '{}',
    PRIMARY KEY (guild_id),
    FOREIGN KEY (guild_id)
        REFERENCES global_config (guild_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS timers
(
    id serial NOT NULL,
    guild_id bigint NOT NULL,
    user_id bigint NOT NULL,
    channel_id bigint,
    event text NOT NULL,
    expires bigint NOT NULL,
    notes text,
    PRIMARY KEY (id),
    FOREIGN KEY (guild_id)
        REFERENCES global_config (guild_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS button_roles
(
    guild_id bigint NOT NULL,
    entry_id serial NOT NULL,
    channel_id bigint NOT NULL,
    msg_id bigint NOT NULL,
    emoji text NOT NULL,
    buttonlabel text,
    buttonstyle text,
    role_id bigint NOT NULL,
    add_title text,
    add_desc text,
    remove_title text,
    remove_desc text,
    PRIMARY KEY (guild_id, entry_id),
    FOREIGN KEY (guild_id)
        REFERENCES global_config (guild_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tags
(
    guild_id bigint NOT NULL,
    tagname text NOT NULL,
    owner_id bigint NOT NULL,
    creator_id bigint, -- This may be null for tags that were not tracked for this.
    uses integer NOT NULL DEFAULT 0,
    aliases text[],
    content text NOT NULL,
    PRIMARY KEY (guild_id, tagname),
    FOREIGN KEY (guild_id)
        REFERENCES global_config (guild_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS log_config
(
    guild_id bigint NOT NULL,
    log_channels json,
    color bool NOT NULL DEFAULT true,
    PRIMARY KEY (guild_id),
    FOREIGN KEY (guild_id)
        REFERENCES global_config (guild_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS starboard
(
    guild_id bigint NOT NULL,
    is_enabled bool NOT NULL DEFAULT false,
    star_limit smallint NOT NULL DEFAULT 5,
    channel_id bigint,
    excluded_channels bigint[] DEFAULT '{}',
    PRIMARY KEY (guild_id),
    FOREIGN KEY (guild_id)
        REFERENCES global_config (guild_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS starboard_entries
(
    guild_id bigint NOT NULL,
    channel_id bigint NOT NULL,
    orig_msg_id bigint NOT NULL,
    entry_msg_id bigint NOT NULL,
    PRIMARY KEY (guild_id, channel_id, orig_msg_id),
    FOREIGN KEY (guild_id)
        REFERENCES global_config (guild_id)
        ON DELETE CASCADE
);