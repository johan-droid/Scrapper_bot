-- Function to increment daily stats atomically (Upsert logic)
CREATE OR REPLACE FUNCTION increment_daily_stats(row_date DATE)
RETURNS void AS $$
BEGIN
    INSERT INTO daily_stats (date, posts_count)
    VALUES (row_date, 1)
    ON CONFLICT (date)
    DO UPDATE SET posts_count = daily_stats.posts_count + 1;
END;
$$ LANGUAGE plpgsql;

-- Function to increment total bot stats atomically
CREATE OR REPLACE FUNCTION increment_bot_stats()
RETURNS void AS $$
BEGIN
    UPDATE bot_stats SET total_posts_all_time = total_posts_all_time + 1;
END;
$$ LANGUAGE plpgsql;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_posted_news_lookup ON posted_news (normalized_title, posted_date);
