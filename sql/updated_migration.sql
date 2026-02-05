-- =========================================================
-- UPDATED MIGRATION SCRIPT FOR GITHUB ACTIONS BOT
-- Run this in Supabase SQL Editor to ensure your DB is ready
-- =========================================================

-- 1. Safely add missing columns to 'posted_news'
DO $$ 
BEGIN 
    -- Add article_url (Original source URL)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='posted_news' AND column_name='article_url') THEN
        ALTER TABLE posted_news ADD COLUMN article_url TEXT;
        RAISE NOTICE 'Added article_url column';
    END IF;

    -- Add telegraph_url (Telegraph page URL)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='posted_news' AND column_name='telegraph_url') THEN
        ALTER TABLE posted_news ADD COLUMN telegraph_url TEXT;
        RAISE NOTICE 'Added telegraph_url column';
    END IF;

    -- Add status (sent/failed/attempted)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='posted_news' AND column_name='status') THEN
        ALTER TABLE posted_news ADD COLUMN status TEXT DEFAULT 'sent';
        RAISE NOTICE 'Added status column';
    END IF;

    -- Add channel_type if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='posted_news' AND column_name='channel_type') THEN
        ALTER TABLE posted_news ADD COLUMN channel_type TEXT DEFAULT 'anime';
        RAISE NOTICE 'Added channel_type column';
    END IF;
END $$;

-- 1.5 Fix bot_stats table (Add missing column)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bot_stats' AND column_name='last_run_at') THEN
        ALTER TABLE bot_stats ADD COLUMN last_run_at TIMESTAMPTZ DEFAULT NOW();
        RAISE NOTICE 'Added last_run_at column to bot_stats';
    END IF;
END $$;

-- 2. Ensure atomic increment functions are up to date
CREATE OR REPLACE FUNCTION increment_daily_stats(row_date DATE)
RETURNS VOID AS $$
BEGIN
    INSERT INTO daily_stats (date, posts_count)
    VALUES (row_date, 1)
    ON CONFLICT (date)
    DO UPDATE SET 
        posts_count = daily_stats.posts_count + 1,
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_bot_stats()
RETURNS VOID AS $$
BEGIN
    -- Ensure at least one row exists
    INSERT INTO bot_stats (id, total_posts_all_time, last_run_at)
    VALUES (1, 1, NOW())
    ON CONFLICT (id) DO UPDATE SET 
        total_posts_all_time = bot_stats.total_posts_all_time + 1,
        last_run_at = NOW(),
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- 3. Ensure 'runs' table has correct columns for new reporting
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='runs' AND column_name='source_counts') THEN
        ALTER TABLE runs ADD COLUMN source_counts JSONB;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='runs' AND column_name='posts_sent') THEN
        ALTER TABLE runs ADD COLUMN posts_sent INTEGER DEFAULT 0;
    END IF;
END $$;

-- 4. Create Indexes for Performance (Idempotent)
CREATE INDEX IF NOT EXISTS idx_posted_news_lookup ON posted_news (normalized_title, posted_date);
CREATE INDEX IF NOT EXISTS idx_posted_news_date ON posted_news (posted_date DESC);
CREATE INDEX IF NOT EXISTS idx_posted_news_status ON posted_news (status, posted_date);
CREATE INDEX IF NOT EXISTS idx_runs_date_slot ON runs (date, slot);

-- 5. Update Constraint for 2-Hour Slots (0-11)
DO $$
BEGIN
    ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_slot_check;
    ALTER TABLE runs ADD CONSTRAINT runs_slot_check CHECK (slot >= 0 AND slot <= 11);
    RAISE NOTICE 'Updated runs_slot_check constraint';
EXCEPTION
    WHEN others THEN
        RAISE NOTICE 'Constraint update skipped/failed: %', SQLERRM;
END $$;

-- 6. Force schema cache reload (Important for API)
NOTIFY pgrst, 'reload config';

-- 7. Add Auto-Cleanup Function (Optimized for Free Tier)
-- Removes data older than 30 days to stay within 500MB limit
CREATE OR REPLACE FUNCTION cleanup_old_data()
RETURNS VOID AS $$
BEGIN
    -- Delete old posted news (keep last 30 days)
    DELETE FROM posted_news 
    WHERE posted_date < CURRENT_DATE - INTERVAL '30 days';
    
    -- Delete old world news posts
    DELETE FROM world_news_posts 
    WHERE posted_date < CURRENT_DATE - INTERVAL '30 days';

    -- Delete old runs history
    DELETE FROM runs 
    WHERE date < CURRENT_DATE - INTERVAL '30 days';
    
    -- Delete old image processing logs
    DELETE FROM image_processing_logs
    WHERE created_at < NOW() - INTERVAL '30 days';
    
    -- Delete old channel metrics
    DELETE FROM channel_metrics
    WHERE date < CURRENT_DATE - INTERVAL '30 days';
END;
$$ LANGUAGE plpgsql;
