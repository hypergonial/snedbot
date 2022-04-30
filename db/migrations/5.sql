-- Convert moderation config into using bitfield

ALTER TABLE mod_config
DROP dm_users_on_punish;

ALTER TABLE mod_config
DROP is_ephemeral;

ALTER TABLE mod_config
ADD flags bigint NOT NULL DEFAULT 1;