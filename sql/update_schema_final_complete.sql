-- COMPLETE Supabase Database Schema Update for Anime-Only Bot
-- This script handles ALL missing columns and updates the entire database structure
-- Final comprehensive fix for anime-only migration

-- ================================================================
-- STEP 1: EXAMINE CURRENT DATABASE STRUCTURE
-- ================================================================

-- First, let's see what tables and columns actually exist
SELECT 'Current bot_stats columns:' as info;
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'bot_stats' 
ORDER BY ordinal_position;

SELECT 'Current daily_stats columns:' as info;
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'daily_stats' 
ORDER BY ordinal_position;

SELECT 'Current posted_news columns:' as info;
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'posted_news' 
ORDER BY ordinal_position;

-- ================================================================
-- STEP 2: CREATE ALL MISSING COLUMNS SAFELY
-- ================================================================

-- Add missing columns to bot_stats table
DO $$
BEGIN
    -- Check and add total_anime_posts
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'bot_stats' 
        AND column_name = 'total_anime_posts'
    ) THEN
        ALTER TABLE bot_stats ADD COLUMN total_anime_posts INTEGER DEFAULT 0;
        RAISE NOTICE 'Added total_anime_posts column to bot_stats';
    END IF;
    
    -- Check and add total_world_posts
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'bot_stats' 
        AND column_name = 'total_world_posts'
    ) THEN
        ALTER TABLE bot_stats ADD COLUMN total_world_posts INTEGER DEFAULT 0;
        RAISE NOTICE 'Added total_world_posts column to bot_stats';
    END IF;
    
    -- Check and add last_updated
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'bot_stats' 
        AND column_name = 'last_updated'
    ) THEN
        ALTER TABLE bot_stats ADD COLUMN last_updated TIMESTAMP DEFAULT NOW();
        RAISE NOTICE 'Added last_updated column to bot_stats';
    END IF;
    
    -- Check and add config_version
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'bot_stats' 
        AND column_name = 'config_version'
    ) THEN
        ALTER TABLE bot_stats ADD COLUMN config_version VARCHAR(50) DEFAULT '1.0';
        RAISE NOTICE 'Added config_version column to bot_stats';
    END IF;
    
    -- Check and add notes
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'bot_stats' 
        AND column_name = 'notes'
    ) THEN
        ALTER TABLE bot_stats ADD COLUMN notes TEXT;
        RAISE NOTICE 'Added notes column to bot_stats';
    END IF;
    
    -- Check and add id if missing (primary key)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'bot_stats' 
        AND column_name = 'id'
    ) THEN
        ALTER TABLE bot_stats ADD COLUMN id SERIAL PRIMARY KEY;
        RAISE NOTICE 'Added id column to bot_stats';
    END IF;
END $$;

-- Add missing columns to daily_stats table
DO $$
BEGIN
    -- Check and add anime_posts
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'daily_stats' 
        AND column_name = 'anime_posts'
    ) THEN
        ALTER TABLE daily_stats ADD COLUMN anime_posts INTEGER DEFAULT 0;
        RAISE NOTICE 'Added anime_posts column to daily_stats';
    END IF;
    
    -- Check and add world_posts
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'daily_stats' 
        AND column_name = 'world_posts'
    ) THEN
        ALTER TABLE daily_stats ADD COLUMN world_posts INTEGER DEFAULT 0;
        RAISE NOTICE 'Added world_posts column to daily_stats';
    END IF;
    
    -- Check and add updated_at
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'daily_stats' 
        AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE daily_stats ADD COLUMN updated_at TIMESTAMP DEFAULT NOW();
        RAISE NOTICE 'Added updated_at column to daily_stats';
    END IF;
    
    -- Check and add date if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'daily_stats' 
        AND column_name = 'date'
    ) THEN
        ALTER TABLE daily_stats ADD COLUMN date DATE PRIMARY KEY;
        RAISE NOTICE 'Added date column to daily_stats';
    END IF;
    
    -- Check and add posts_count if missing
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'daily_stats' 
        AND column_name = 'posts_count'
    ) THEN
        ALTER TABLE daily_stats ADD COLUMN posts_count INTEGER DEFAULT 0;
        RAISE NOTICE 'Added posts_count column to daily_stats';
    END IF;
END $$;

-- Add missing columns to posted_news table
DO $$
BEGIN
    -- Check and add channel_type
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'channel_type'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN channel_type VARCHAR(20) DEFAULT 'anime';
        RAISE NOTICE 'Added channel_type column to posted_news';
    END IF;
    
    -- Check and add other essential columns
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'id'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN id SERIAL PRIMARY KEY;
        RAISE NOTICE 'Added id column to posted_news';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'normalized_title'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN normalized_title TEXT;
        RAISE NOTICE 'Added normalized_title column to posted_news';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'full_title'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN full_title TEXT;
        RAISE NOTICE 'Added full_title column to posted_news';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'posted_date'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN posted_date DATE;
        RAISE NOTICE 'Added posted_date column to posted_news';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'posted_at'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN posted_at TIMESTAMP;
        RAISE NOTICE 'Added posted_at column to posted_news';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'source'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN source VARCHAR(50);
        RAISE NOTICE 'Added source column to posted_news';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'slot'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN slot INTEGER;
        RAISE NOTICE 'Added slot column to posted_news';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'category'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN category VARCHAR(100);
        RAISE NOTICE 'Added category column to posted_news';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'status'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN status VARCHAR(20) DEFAULT 'sent';
        RAISE NOTICE 'Added status column to posted_news';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'article_url'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN article_url TEXT;
        RAISE NOTICE 'Added article_url column to posted_news';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'posted_news' 
        AND column_name = 'telegraph_url'
    ) THEN
        ALTER TABLE posted_news ADD COLUMN telegraph_url TEXT;
        RAISE NOTICE 'Added telegraph_url column to posted_news';
    END IF;
END $$;

-- ================================================================
-- STEP 3: MIGRATE DATA TO ANIME-ONLY
-- ================================================================

-- Update bot_stats table to consolidate world posts into anime posts
UPDATE bot_stats 
SET 
    total_anime_posts = COALESCE(total_anime_posts, 0) + COALESCE(total_world_posts, 0),
    total_world_posts = 0,
    last_updated = NOW(),
    config_version = '2.0-anime-only',
    notes = 'Removed world news functionality, focused on anime content with Telegraph integration'
WHERE COALESCE(id, 1) = 1;

-- Update daily_stats table to remove world news references
UPDATE daily_stats 
SET 
    anime_posts = COALESCE(anime_posts, 0) + COALESCE(world_posts, 0),
    world_posts = 0,
    updated_at = NOW()
WHERE COALESCE(world_posts, 0) > 0;

-- Update posted_news table to set all records as anime type
UPDATE posted_news 
SET channel_type = 'anime' 
WHERE channel_type = 'world' OR channel_type IS NULL;

-- ================================================================
-- STEP 4: CREATE INDEXES FOR PERFORMANCE
-- ================================================================

-- Add indexes for better performance with anime content
CREATE INDEX IF NOT EXISTS idx_posted_news_anime ON posted_news(channel_type, posted_date);
CREATE INDEX IF NOT EXISTS idx_posted_news_source ON posted_news(source, posted_date);
CREATE INDEX IF NOT EXISTS idx_posted_news_date ON posted_news(posted_date);
CREATE INDEX IF NOT EXISTS idx_daily_stats_anime ON daily_stats(date, anime_posts);
CREATE INDEX IF NOT EXISTS idx_daily_stats_date ON daily_stats(date);

-- ================================================================
-- STEP 5: CREATE VIEWS FOR REPORTING
-- ================================================================

-- Create a summary view for anime posts
CREATE OR REPLACE VIEW anime_posts_summary AS
SELECT 
    date,
    anime_posts,
    posts_count,
    updated_at
FROM daily_stats 
ORDER BY date DESC;

-- ================================================================
-- STEP 6: VERIFICATION AND REPORTING
-- ================================================================

-- Show final database state
SELECT '=== FINAL DATABASE STATE ===' as status;

SELECT 
    'Bot Stats Table' as table_name,
    COUNT(*) as records,
    COALESCE(SUM(total_anime_posts), 0) as total_anime_posts,
    COALESCE(SUM(total_world_posts), 0) as total_world_posts,
    MAX(config_version) as config_version
FROM bot_stats;

SELECT 
    'Daily Stats Table' as table_name,
    COUNT(*) as records,
    COALESCE(SUM(anime_posts), 0) as total_anime_posts,
    COALESCE(SUM(world_posts), 0) as total_world_posts
FROM daily_stats;

SELECT 
    'Posted News Table' as table_name,
    COUNT(*) as total_records,
    COUNT(DISTINCT source) as unique_sources,
    COUNT(DISTINCT channel_type) as channel_types,
    MIN(posted_date) as earliest_post,
    MAX(posted_date) as latest_post
FROM posted_news;

-- Show channel type distribution
SELECT 
    channel_type,
    COUNT(*) as record_count
FROM posted_news 
GROUP BY channel_type
ORDER BY channel_type;

-- ================================================================
-- STEP 7: CLEANUP (OPTIONAL)
-- ================================================================

-- Clean up old world news data older than 30 days (optional - commented out)
-- DELETE FROM posted_news 
-- WHERE channel_type = 'world' 
-- AND posted_date < CURRENT_DATE - INTERVAL '30 days';

COMMIT;

-- ================================================================
-- SUCCESS MESSAGE
-- ================================================================

SELECT '🎉 DATABASE MIGRATION COMPLETED SUCCESSFULLY! 🎉' as final_status;
SELECT '✅ All missing columns created' as step1;
SELECT '✅ Data migrated to anime-only' as step2;
SELECT '✅ Performance indexes added' as step3;
SELECT '✅ Reporting views created' as step4;
SELECT '✅ Database ready for anime-only bot' as step5;
