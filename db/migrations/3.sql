-- Add support for customizable rolebutton confirm prompts and rolebutton modes

ALTER TABLE button_roles
ADD add_title text;

ALTER TABLE button_roles
ADD add_desc text;

ALTER TABLE button_roles
ADD remove_title text;

ALTER TABLE button_roles
ADD remove_desc text;

ALTER TABLE button_roles
ADD mode smallint NOT NULL DEFAULT 0;

ALTER TABLE button_roles
RENAME COLUMN buttonlabel TO label;

ALTER TABLE button_roles
RENAME COLUMN buttonstyle TO style;