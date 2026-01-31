-- ========================================
-- Supabase Schema Update for Enhanced News Bot
-- ========================================
-- Includes support for World News Scraper and Multi-Channel functionality
-- ========================================

-- 1. Update existing posted_news table to support new features
ALTER TABLE posted_news 
ADD COLUMN IF NOT EXISTS channel_type VARCHAR(20) DEFAULT 'general',
ADD COLUMN IF NOT EXISTS has_image BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS image_url TEXT,
ADD COLUMN IF NOT EXISTS source_priority INTEGER DEFAULT 3,
ADD COLUMN IF NOT EXISTS content_type VARCHAR(20) DEFAULT 'text',
ADD COLUMN IF NOT EXISTS processing_time INTEGER,
ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;

-- 2. Create new table for world news tracking
CREATE TABLE IF NOT EXISTS world_news_posts (
    id BIGSERIAL PRIMARY KEY,
    normalized_title TEXT NOT NULL,
    full_title TEXT NOT NULL,
    article_url TEXT NOT NULL,
    source VARCHAR(50) NOT NULL,
    source_description TEXT,
    country VARCHAR(50),
    priority INTEGER DEFAULT 3,
    image_url TEXT,
    image_processed BOOLEAN DEFAULT FALSE,
    image_size INTEGER,
    posted_date DATE NOT NULL,
    posted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    run_id BIGINT REFERENCES runs(id),
    slot INTEGER,
    channel_id VARCHAR(50),
    content_type VARCHAR(20) DEFAULT 'text',
    processing_time INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Create index for world news posts
CREATE INDEX IF NOT EXISTS idx_world_news_posts_date ON world_news_posts(posted_date);
CREATE INDEX IF NOT EXISTS idx_world_news_posts_source ON world_news_posts(source);
CREATE INDEX IF NOT EXISTS idx_world_news_posts_priority ON world_news_posts(priority);
CREATE INDEX IF NOT EXISTS idx_world_news_posts_normalized_title ON world_news_posts(normalized_title);

-- 4. Create table for image processing logs
CREATE TABLE IF NOT EXISTS image_processing_logs (
    id BIGSERIAL PRIMARY KEY,
    article_url TEXT NOT NULL,
    original_image_url TEXT,
    processed_image_url TEXT,
    original_size INTEGER,
    processed_size INTEGER,
    processing_time INTEGER,
    status VARCHAR(20) NOT NULL, -- 'success', 'failed', 'skipped'
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. Create table for channel performance metrics
CREATE TABLE IF NOT EXISTS channel_metrics (
    id BIGSERIAL PRIMARY KEY,
    channel_type VARCHAR(20) NOT NULL, -- 'general', 'world', 'entertainment'
    channel_id VARCHAR(50),
    posts_sent INTEGER DEFAULT 0,
    images_sent INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    avg_processing_time INTEGER,
    date DATE NOT NULL,
    hour INTEGER, -- For hourly tracking
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(channel_type, channel_id, date, hour)
);

-- 6. Create table for source health monitoring
CREATE TABLE IF NOT EXISTS source_health (
    id BIGSERIAL PRIMARY KEY,
    source_name VARCHAR(50) NOT NULL UNIQUE,
    source_type VARCHAR(20) NOT NULL, -- 'general', 'world', 'entertainment'
    rss_url TEXT NOT NULL,
    last_successful_fetch TIMESTAMP WITH TIME ZONE,
    last_failed_fetch TIMESTAMP WITH TIME ZONE,
    consecutive_failures INTEGER DEFAULT 0,
    total_articles_fetched INTEGER DEFAULT 0,
    avg_articles_per_fetch INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active', -- 'active', 'degraded', 'inactive'
    error_message TEXT,
    response_time INTEGER, -- in milliseconds
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 7. Insert world news sources into source health table
INSERT INTO source_health (source_name, source_type, rss_url) VALUES
('BBC World', 'world', 'http://feeds.bbci.co.uk/news/world/rss.xml'),
('Reuters World', 'world', 'https://www.reuters.com/rssFeed/worldNews'),
('Al Jazeera', 'world', 'https://www.aljazeera.com/xml/rss/all.xml'),
('CNN World', 'world', 'http://rss.cnn.com/rss/edition_world.rss'),
('The Guardian World', 'world', 'https://www.theguardian.com/world/rss'),
('AP World', 'world', 'https://apnews.com/rss/world-news'),
('NPR International', 'world', 'https://feeds.npr.org/1001/rss.xml'),
('Deutsche Welle', 'world', 'https://www.dw.com/en/rss/rss-en-all'),
('France 24', 'world', 'https://www.france24.com/en/rss'),
('CBC World', 'world', 'https://www.cbc.ca/cmlink/rss-world')
ON CONFLICT (source_name) DO NOTHING;

-- 8. Update existing general news sources in source health
INSERT INTO source_health (source_name, source_type, rss_url) VALUES
('NewsLaundry', 'general', 'https://www.newslaundry.com/feed'),
('The Wire', 'general', 'https://thewire.in/feed'),
('Scroll.in', 'general', 'https://scroll.in/feed'),
('The Print', 'general', 'https://theprint.in/feed'),
('ProPublica', 'general', 'https://www.propublica.org/feeds/propublica/main')
ON CONFLICT (source_name) DO UPDATE SET
source_type = EXCLUDED.source_type,
rss_url = EXCLUDED.rss_url;

-- 9. Create function to update channel metrics
CREATE OR REPLACE FUNCTION update_channel_metrics(
    p_channel_type VARCHAR(20),
    p_channel_id VARCHAR(50),
    p_posts_sent INTEGER DEFAULT 0,
    p_images_sent INTEGER DEFAULT 0,
    p_errors_count INTEGER DEFAULT 0,
    p_avg_processing_time INTEGER DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO channel_metrics (
        channel_type, channel_id, posts_sent, images_sent, errors_count, avg_processing_time, date, hour
    ) VALUES (
        p_channel_type, p_channel_id, p_posts_sent, p_images_sent, p_errors_count, p_avg_processing_time,
        CURRENT_DATE, EXTRACT(HOUR FROM NOW())
    )
    ON CONFLICT (channel_type, channel_id, date, hour)
    DO UPDATE SET
        posts_sent = channel_metrics.posts_sent + EXCLUDED.posts_sent,
        images_sent = channel_metrics.images_sent + EXCLUDED.images_sent,
        errors_count = channel_metrics.errors_count + EXCLUDED.errors_count,
        avg_processing_time = COALESCE(EXCLUDED.avg_processing_time, channel_metrics.avg_processing_time),
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- 10. Create function to log image processing
CREATE OR REPLACE FUNCTION log_image_processing(
    p_article_url TEXT,
    p_original_image_url TEXT DEFAULT NULL,
    p_processed_image_url TEXT DEFAULT NULL,
    p_original_size INTEGER DEFAULT NULL,
    p_processed_size INTEGER DEFAULT NULL,
    p_processing_time INTEGER DEFAULT NULL,
    p_status VARCHAR(20) DEFAULT 'success',
    p_error_message TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO image_processing_logs (
        article_url, original_image_url, processed_image_url, original_size, processed_size,
        processing_time, status, error_message
    ) VALUES (
        p_article_url, p_original_image_url, p_processed_image_url, p_original_size, p_processed_size,
        p_processing_time, p_status, p_error_message
    );
END;
$$ LANGUAGE plpgsql;

-- 11. Create function to update source health
CREATE OR REPLACE FUNCTION update_source_health(
    p_source_name VARCHAR(50),
    p_success BOOLEAN DEFAULT TRUE,
    p_response_time INTEGER DEFAULT NULL,
    p_articles_count INTEGER DEFAULT 0,
    p_error_message TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    IF p_success THEN
        UPDATE source_health SET
            last_successful_fetch = NOW(),
            consecutive_failures = 0,
            total_articles_fetched = total_articles_fetched + p_articles_count,
            avg_articles_per_fetch = CASE 
                WHEN total_articles_fetched + p_articles_count > 0 
                THEN ROUND((total_articles_fetched + p_articles_count)::NUMERIC / 
                         (GREATEST(total_articles_fetched + p_articles_count, 1)))
                ELSE 0 
            END,
            response_time = p_response_time,
            status = CASE 
                WHEN consecutive_failures = 0 THEN 'active'
                ELSE 'degraded'
            END,
            error_message = NULL,
            updated_at = NOW()
        WHERE source_name = p_source_name;
    ELSE
        UPDATE source_health SET
            last_failed_fetch = NOW(),
            consecutive_failures = consecutive_failures + 1,
            status = CASE 
                WHEN consecutive_failures >= 3 THEN 'inactive'
                WHEN consecutive_failures >= 1 THEN 'degraded'
                ELSE 'active'
            END,
            error_message = p_error_message,
            updated_at = NOW()
        WHERE source_name = p_source_name;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- 12. Create view for comprehensive bot statistics
CREATE OR REPLACE VIEW bot_statistics AS
SELECT 
    'general' as channel_type,
    COUNT(DISTINCT DATE(posted_date)) as active_days,
    COUNT(*) as total_posts,
    COUNT(CASE WHEN has_image = TRUE THEN 1 END) as posts_with_images,
    AVG(processing_time) as avg_processing_time,
    MAX(posted_at) as last_post_time
FROM posted_news 
WHERE posted_date >= CURRENT_DATE - INTERVAL '30 days'

UNION ALL

SELECT 
    'world' as channel_type,
    COUNT(DISTINCT DATE(posted_date)) as active_days,
    COUNT(*) as total_posts,
    COUNT(CASE WHEN image_processed = TRUE THEN 1 END) as posts_with_images,
    AVG(processing_time) as avg_processing_time,
    MAX(posted_at) as last_post_time
FROM world_news_posts 
WHERE posted_date >= CURRENT_DATE - INTERVAL '30 days'

UNION ALL

SELECT 
    'entertainment' as channel_type,
    COUNT(DISTINCT DATE(posted_date)) as active_days,
    COUNT(*) as total_posts,
    0 as posts_with_images,
    0 as avg_processing_time,
    MAX(posted_at) as last_post_time
FROM posted_news 
WHERE posted_date >= CURRENT_DATE - INTERVAL '30 days'
AND source IN ('ANN', 'ANN_DC', 'DCW', 'TMS', 'FANDOM', 'ANI', 'MAL', 'CR', 'AC', 'HONEY');

-- 13. Create view for source health dashboard
CREATE OR REPLACE VIEW source_health_dashboard AS
SELECT 
    sh.source_name,
    sh.source_type,
    sh.rss_url,
    sh.status,
    sh.consecutive_failures,
    sh.total_articles_fetched,
    sh.avg_articles_per_fetch,
    sh.response_time,
    sh.last_successful_fetch,
    sh.last_failed_fetch,
    sh.error_message,
    CASE 
        WHEN sh.last_successful_fetch > NOW() - INTERVAL '1 hour' THEN '🟢 Online'
        WHEN sh.last_successful_fetch > NOW() - INTERVAL '6 hours' THEN '🟡 Slow'
        WHEN sh.last_successful_fetch > NOW() - INTERVAL '24 hours' THEN '🟠 Degraded'
        ELSE '🔴 Offline'
    END as health_indicator
FROM source_health sh
ORDER BY sh.source_type, sh.source_name;

-- 14. Add RLS (Row Level Security) policies for new tables
ALTER TABLE world_news_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE image_processing_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_health ENABLE ROW LEVEL SECURITY;

-- Policy for world_news_posts (similar to posted_news)
CREATE POLICY "Users can view their own world news posts" ON world_news_posts
    FOR SELECT USING (true);

CREATE POLICY "Service can insert world news posts" ON world_news_posts
    FOR INSERT WITH CHECK (true);

-- Policy for image_processing_logs
CREATE POLICY "Users can view image processing logs" ON image_processing_logs
    FOR SELECT USING (true);

CREATE POLICY "Service can insert image processing logs" ON image_processing_logs
    FOR INSERT WITH CHECK (true);

-- Policy for channel_metrics
CREATE POLICY "Users can view channel metrics" ON channel_metrics
    FOR SELECT USING (true);

CREATE POLICY "Service can manage channel metrics" ON channel_metrics
    FOR ALL USING (true);

-- Policy for source_health
CREATE POLICY "Users can view source health" ON source_health
    FOR SELECT USING (true);

CREATE POLICY "Service can manage source health" ON source_health
    FOR ALL USING (true);

-- 15. Create trigger for updated_at timestamp
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers to new tables
CREATE TRIGGER set_world_news_posts_timestamp
    BEFORE UPDATE ON world_news_posts
    FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

CREATE TRIGGER set_channel_metrics_timestamp
    BEFORE UPDATE ON channel_metrics
    FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

CREATE TRIGGER set_source_health_timestamp
    BEFORE UPDATE ON source_health
    FOR EACH ROW EXECUTE FUNCTION trigger_set_timestamp();

-- ========================================
-- Migration Complete
-- ========================================
-- New Features Supported:
-- ✅ World news tracking with image processing
-- ✅ Multi-channel performance metrics
-- ✅ Source health monitoring
-- ✅ Image processing logs
-- ✅ Comprehensive statistics dashboard
-- ✅ Enhanced duplicate prevention
-- ✅ Row Level Security
-- ========================================
