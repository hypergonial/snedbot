-- Replace user flags with bitfield format.

ALTER TABLE users
DROP flags;

ALTER TABLE users
ADD flags bigint NOT NULL DEFAULT 0;

-- Add field for misc. user data as json format

ALTER TABLE users
ADD data json NOT NULL DEFAULT '{}';