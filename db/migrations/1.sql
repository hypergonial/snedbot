-- Migration of schema from Sned V1


-- Obsolete or removed functionality
DROP TABLE IF EXISTS public.guild_blacklist;
DROP TABLE IF EXISTS public.permissions;
DROP TABLE IF EXISTS public.modules;
DROP TABLE IF EXISTS public.priviliged;
DROP TABLE IF EXISTS public.events;
DROP TABLE IF EXISTS public.matchmaking_config;
DROP TABLE IF EXISTS public.matchmaking_listings;
DROP TABLE IF EXISTS public.ktp;

-- Irrelevant for slash commands
ALTER TABLE mod_config
DROP clean_up_mod_commands;

-- New feature
ALTER TABLE mod_config
ADD is_ephemeral bigint NOT NULL DEFAULT false;

-- Payloads changed significantly
DELETE automod_policies FROM mod_config;
DELETE * FROM log_config;

-- New feature
ALTER TABLE log_config
ADD color bool NOT NULL DEFAULT true;

-- More consistent naming scheme
ALTER TABLE tags
RENAME COLUMN tag_name TO tagname;
ALTER TABLE tags
RENAME COLUMN tag_owner_id TO owner_id;
ALTER TABLE tags
RENAME COLUMN tag_aliases TO aliases;
ALTER TABLE tags
RENAME COLUMN tag_content TO content;

-- Track tag creator
ALTER TABLE tags
ADD creator_id bigint;

-- Add tag stats
ALTER TABLE tags
ADD uses integer NOT NULL DEFAULT 0;