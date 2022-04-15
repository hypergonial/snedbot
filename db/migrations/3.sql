-- Add support for customizable rolebutton confirm prompts

ALTER TABLE button_roles
ADD add_title text;

ALTER TABLE button_roles
ADD add_desc text;

ALTER TABLE button_roles
ADD remove_title text;

ALTER TABLE button_roles
ADD remove_desc text;