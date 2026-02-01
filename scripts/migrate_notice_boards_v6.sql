-- Migration v6: Remove unique constraint on ICO
-- ICO can be shared by city districts (městské části) and their parent city
-- E.g., Město Plzeň and all MČ Plzeň share the same ICO

-- Drop the unique index on ICO
DROP INDEX IF EXISTS idx_notice_boards_ico_unique;

-- Keep the non-unique index for lookups
-- (idx_notice_boards_ico already exists as a regular index)
