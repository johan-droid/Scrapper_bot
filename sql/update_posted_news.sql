-- Update posted_news table for robust tracking and deduplication

-- 1. Add status column to track delivery state
-- This allows us to record an item as 'attempted' before sending to Telegram
-- ensuring that even if the bot crashes, we don't retry it blindly (or can handle retries smarter).
ALTER TABLE posted_news 
ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'sent';

-- 2. Add index on date_ist (or posted_date/posted_at) for faster queries
-- The user requested `date_ist`, but the current schema uses `posted_date` (TEXT YYYY-MM-DD) or `posted_at` (TIMESTAMPTZ).
-- We'll verify the schema usage in python, but adding an index on `posted_at` is generally good for time-based queries.
-- If `date_ist` is a specific column the user wants, we can add it, but `posted_at` converted to IST is likely what is meant or we should add a generated column.
-- For now, let's index `posted_at` and `normalized_title`.

CREATE INDEX IF NOT EXISTS idx_posted_news_posted_at ON posted_news(posted_at);
CREATE INDEX IF NOT EXISTS idx_posted_news_normalized_title ON posted_news(normalized_title);

-- 3. (Optional) If the user definitely wants a 'date_ist' column for partitioning/cleanup (though we are removing cleanup):
-- ALTER TABLE posted_news ADD COLUMN IF NOT EXISTS date_ist TIMESTAMP WITH TIME ZONE DEFAULT NOW();
