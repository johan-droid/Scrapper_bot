-- RPC Function for daily stats
CREATE OR REPLACE FUNCTION increment_daily_stats(row_date DATE)
RETURNS void AS $$
UPDATE daily_stats SET posts_count = posts_count + 1 WHERE date = row_date;
$$ LANGUAGE sql;

-- RPC Function for bot stats
CREATE OR REPLACE FUNCTION increment_bot_stats()
RETURNS void AS $$
UPDATE bot_stats SET total_posts_all_time = total_posts_all_time + 1;
$$ LANGUAGE sql;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_posted_news_lookup ON posted_news (normalized_title, posted_date);
