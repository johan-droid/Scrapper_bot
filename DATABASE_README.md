# Database Setup Guide

## Single File Setup

All database schema has been consolidated into **`database_setup.sql`**

### Quick Setup

1. **Go to Supabase Dashboard**
   - Navigate to your project
   - Click on "SQL Editor" in the left sidebar

2. **Run the Schema**
   - Open `database_setup.sql`
   - Copy the entire contents
   - Paste into Supabase SQL Editor
   - Click "Run" or press `Ctrl+Enter`

3. **Verify Setup**
   ```sql
   -- Check tables were created
   SELECT table_name FROM information_schema.tables 
   WHERE table_schema = 'public';
   
   -- Should show: bot_stats, daily_stats, runs, posted_news
   ```

### What's Included

- ✅ **Core Tables**: bot_stats, daily_stats, runs, posted_news
- ✅ **Indexes**: Optimized for fast lookups
- ✅ **Functions**: Atomic increments, duplicate checking, cleanup
- ✅ **Security**: Row Level Security (RLS) policies
- ✅ **Triggers**: Auto-update timestamps
- ✅ **Views**: Analytics and reporting
- ✅ **Merged Channels**: DC + Anime news in single channel type

### Key Features

#### 1. Strong Spam Detection
- Normalized title matching
- Fuzzy matching (85% threshold)
- 7-day deduplication window

#### 2. Status Tracking
- `attempted`: Post recorded before sending
- `sent`: Successfully posted
- `failed`: Send failed

#### 3. Channel Types
- `anime`: Anime + DC news (merged)
- `world`: World/general news

### Maintenance

#### Clean Old Posts (Optional)
```sql
-- Remove posts older than 30 days
SELECT cleanup_old_posts(30);
```

#### Check Source Health
```sql
SELECT * FROM source_health;
```

#### View Recent Activity
```sql
SELECT * FROM recent_activity LIMIT 20;
```

#### Daily Summary
```sql
SELECT * FROM daily_summary;
```

### Troubleshooting

#### If tables already exist
```sql
-- Drop all tables (WARNING: Deletes all data)
DROP TABLE IF EXISTS posted_news CASCADE;
DROP TABLE IF EXISTS runs CASCADE;
DROP TABLE IF EXISTS daily_stats CASCADE;
DROP TABLE IF EXISTS bot_stats CASCADE;

-- Then run database_setup.sql again
```

#### If functions fail
```sql
-- Enable required extension
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### Old Files (Deprecated)

The following files are now obsolete and can be ignored:
- ❌ `setup_supabase.sql` (old version)
- ❌ `supabase_schema.sql` (old version)
- ❌ `sql/add_status_column.sql` (merged)
- ❌ `sql/optimization_updates.sql` (merged)
- ❌ `sql/supabase_schema_update.sql` (merged)
- ❌ `sql/update_posted_news.sql` (merged)

**Use only `database_setup.sql`** - it contains everything you need.

### Environment Variables

Make sure these are set in your `.env` or GitHub Secrets:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
```

### Verification

After setup, the bot should log:
```
[OK] Supabase connected successfully
[LOAD] Loaded X titles from last 7 days
```

If you see these messages, your database is working correctly!
