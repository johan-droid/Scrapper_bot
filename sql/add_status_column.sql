-- Add status column to posted_news table
ALTER TABLE posted_news ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'sent';

-- Updates to existing table structure if needed
-- (The previous CREATE TABLE was missing this column)
