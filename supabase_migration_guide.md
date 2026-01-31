# Supabase Migration Guide

## Overview
This migration adds support for the enhanced news bot with world news scraper, multi-channel functionality, and image processing capabilities.

## 🚀 Quick Migration Steps

### 1. Run the SQL Migration
```sql
-- Execute the entire supabase_schema_update.sql file in your Supabase SQL editor
-- Or run via CLI: supabase db push
```

### 2. Update Environment Variables
Add these to your `.env` file:
```env
WORLD_NEWS_CHANNEL_ID=your_world_news_channel_id_here
```

### 3. Install New Dependencies
```bash
pip install -r requirements.txt
# New packages: Pillow==10.1.0
```

## 📊 New Tables Created

### `world_news_posts`
Tracks world news articles with image processing:
- High-quality article tracking
- Image processing status
- Source priority management
- Channel-specific posting

### `image_processing_logs`
Logs all image processing operations:
- Original vs processed image sizes
- Processing time metrics
- Success/failure tracking
- Error debugging information

### `channel_metrics`
Performance metrics per channel:
- Posts sent per hour
- Images processed
- Error rates
- Processing times

### `source_health`
Real-time source monitoring:
- RSS feed availability
- Response times
- Consecutive failure tracking
- Automatic status updates

## 🔄 Enhanced Existing Tables

### `posted_news` (Updated)
New columns added:
- `channel_type`: 'general', 'world', 'entertainment'
- `has_image`: Boolean flag for image posts
- `image_url`: High-quality image URL
- `source_priority`: Priority ranking (1-3)
- `content_type`: 'text', 'image', 'mixed'
- `processing_time`: Time in milliseconds
- `retry_count`: Retry attempts

## 📈 New Views & Functions

### `bot_statistics` View
Comprehensive 30-day statistics:
- Posts per channel type
- Image processing metrics
- Average processing times
- Last activity timestamps

### `source_health_dashboard` View
Real-time source monitoring:
- Health indicators (🟢🟡🟠🔴)
- Response times
- Failure counts
- Last successful fetch

### Helper Functions
- `update_channel_metrics()`: Track channel performance
- `log_image_processing()`: Log image operations
- `update_source_health()`: Monitor source status

## 🔒 Security Features

### Row Level Security (RLS)
- All new tables have RLS enabled
- Service role full access
- User role read access
- Comprehensive policy coverage

### Data Protection
- Sensitive data properly isolated
- Audit trails maintained
- Access controls enforced

## 📊 Migration Impact

### Before Migration
- Basic news tracking
- Single channel support
- No image processing
- Limited source monitoring

### After Migration
- ✅ Multi-channel support (3 channels)
- ✅ World news with images
- ✅ Advanced source monitoring
- ✅ Performance analytics
- ✅ Image processing logs
- ✅ Health dashboards
- ✅ Enhanced duplicate prevention

## 🛠️ Post-Migration Tasks

### 1. Update Bot Code
Ensure your bot uses the new database functions:
```python
# Example: Update source health
update_source_health('BBC World', True, 250, 5)

# Example: Log image processing
log_image_processing(article_url, original_url, processed_url, 500000, 100000, 1500)
```

### 2. Test New Features
- Run world news scraper
- Test image processing
- Verify channel metrics
- Check source health dashboard

### 3. Monitor Performance
- Check `bot_statistics` view
- Monitor `source_health_dashboard`
- Review `channel_metrics` trends

## 🚨 Rollback Plan

If issues occur, you can rollback by:
```sql
-- Drop new tables
DROP TABLE IF EXISTS world_news_posts;
DROP TABLE IF EXISTS image_processing_logs;
DROP TABLE IF EXISTS channel_metrics;
DROP TABLE IF EXISTS source_health;

-- Drop new columns from posted_news
ALTER TABLE posted_news 
DROP COLUMN IF EXISTS channel_type,
DROP COLUMN IF EXISTS has_image,
DROP COLUMN IF EXISTS image_url,
DROP COLUMN IF EXISTS source_priority,
DROP COLUMN IF EXISTS content_type,
DROP COLUMN IF EXISTS processing_time,
DROP COLUMN IF EXISTS retry_count;

-- Drop views and functions
DROP VIEW IF EXISTS bot_statistics;
DROP VIEW IF EXISTS source_health_dashboard;
DROP FUNCTION IF EXISTS update_channel_metrics;
DROP FUNCTION IF EXISTS log_image_processing;
DROP FUNCTION IF EXISTS update_source_health;
```

## 📞 Support

### Common Issues
1. **Migration fails**: Check for existing conflicting columns
2. **RLS errors**: Ensure service role has proper permissions
3. **Performance**: Add indexes after migration if needed

### Debug Queries
```sql
-- Check migration status
SELECT table_name, column_name, data_type 
FROM information_schema.columns 
WHERE table_name IN ('world_news_posts', 'image_processing_logs', 'channel_metrics', 'source_health');

-- Verify RLS policies
SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual 
FROM pg_policies 
WHERE tablename IN ('world_news_posts', 'image_processing_logs', 'channel_metrics', 'source_health');
```

## ✅ Migration Checklist

- [ ] Backup existing database
- [ ] Run SQL migration script
- [ ] Update environment variables
- [ ] Install new dependencies
- [ ] Test world news scraper
- [ ] Verify image processing
- [ ] Check channel metrics
- [ ] Monitor source health
- [ ] Review bot statistics
- [ ] Update documentation

---

**Migration Complete!** 🎉

Your Supabase database now supports the enhanced news bot with world news scraping, image processing, and comprehensive analytics.
