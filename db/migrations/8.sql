-- Add force_starred field to starboard entries

ALTER TABLE starboard_entries
ADD force_starred bool NOT NULL DEFAULT false;