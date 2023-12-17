-- Rename buttonstyles to better match enum values
UPDATE button_roles SET buttonstyle = 'PRIMARY' WHERE buttonstyle = 'Blurple';
UPDATE button_roles SET buttonstyle = 'SECONDARY' WHERE buttonstyle = 'Grey';
UPDATE button_roles SET buttonstyle = 'SUCCESS' WHERE buttonstyle = 'Green';
UPDATE button_roles SET buttonstyle = 'DANGER' WHERE buttonstyle = 'Red';