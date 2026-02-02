# 🚀 DEPLOYMENT CHECKLIST

## Pre-Deployment Verification

### ✅ All Tests Passed
- [x] Channel Routing Test
- [x] Spam Detection Test  
- [x] Date Filtering Test
- [x] World News Formatting Test

## Step-by-Step Deployment

### 1. Backup Current System ⚠️
```bash
# Backup current bot file
cp animebot.py animebot.py.backup.$(date +%Y%m%d)

# Export current database (if using Supabase)
# Go to Supabase Dashboard → Database → Backups
```

### 2. Update Database Schema 📊
```sql
-- Connect to Supabase SQL Editor
-- Run the entire supabase_schema.sql file
-- This will:
-- ✅ Add status column to posted_news
-- ✅ Create/update indexes
-- ✅ Add atomic increment functions
-- ✅ Set up RLS policies
-- ✅ Create helper views
```

### 3. Update Environment Variables 🔧
Add/verify these in GitHub Actions Secrets:

```
Required:
✅ BOT_TOKEN=your_telegram_bot_token
✅ ANIME_NEWS_CHANNEL_ID=your_anime_news_channel_id
✅ WORLD_NEWS_CHANNEL_ID=your_world_news_channel_id

Optional but Recommended:
⚪ CHAT_ID=your_main_channel_id (fallback)
⚪ ADMIN_ID=your_telegram_user_id (for reports)
⚪ SUPABASE_URL=https://your-project.supabase.co
⚪ SUPABASE_KEY=your_supabase_anon_key
```

### 4. Deploy Fixed Bot Code 🤖
```bash
# Replace animebot.py with the fixed version
# Commit and push to GitHub

git add animebot.py
git commit -m "Fix: Merged DC/Anime channels, proper routing, spam detection"
git push origin main
```

### 5. Verify GitHub Actions Workflow ⚙️
Ensure `.github/workflows/bot_schedule.yml` has all secrets mapped:
```yaml
env:
  BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
  CHAT_ID: ${{ secrets.CHAT_ID }}
  ANIME_NEWS_CHANNEL_ID: ${{ secrets.ANIME_NEWS_CHANNEL_ID }}
  WORLD_NEWS_CHANNEL_ID: ${{ secrets.WORLD_NEWS_CHANNEL_ID }}
  ADMIN_ID: ${{ secrets.ADMIN_ID }}
  SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
  SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}
```

### 6. Test Run (Manual Trigger) 🧪
```
1. Go to GitHub → Actions → "Run Anime News Bot"
2. Click "Run workflow"
3. Select branch: main
4. Click "Run workflow"
5. Monitor logs for:
   ✅ "Supabase connected successfully"
   ✅ "Loaded X titles from last 7 days"
   ✅ "Routing X to WORLD_NEWS_CHANNEL"
   ✅ "Routing X to ANIME_NEWS_CHANNEL"
   ✅ "Sent (Image/Text) to X"
```

### 7. Monitor First Automated Run ⏰
Wait for next scheduled run (every 4 hours):
- Check GitHub Actions logs
- Verify posts in correct channels:
  - Anime + DC news → ANIME_NEWS_CHANNEL_ID
  - World news → WORLD_NEWS_CHANNEL_ID
- Check admin report (if ADMIN_ID set)

### 8. Verify No Duplicates 🚫
Over next 24 hours, monitor for:
- ✅ No duplicate posts within same channel
- ✅ No old news (only today/yesterday)
- ✅ Posts only every 4 hours (6 times daily)

## Post-Deployment Monitoring

### Daily Checks (First Week)
- [ ] Check admin reports
- [ ] Verify channel routing is correct
- [ ] Confirm no spam/duplicates
- [ ] Review GitHub Actions logs

### Weekly Checks
- [ ] Database cleanup (optional):
```sql
-- Remove posts older than 30 days
DELETE FROM posted_news WHERE created_at < NOW() - INTERVAL '30 days';
```
- [ ] Check source health via admin reports
- [ ] Review daily summary stats

## Rollback Plan (If Issues Occur)

### Quick Rollback
```bash
# Restore backup
cp animebot.py.backup.YYYYMMDD animebot.py
git add animebot.py
git commit -m "Rollback to previous version"
git push origin main
```

### Database Rollback
```sql
-- If you need to revert database changes
-- (Keep a backup of old schema before migration)
```

## Common Issues & Solutions

### Issue 1: World news still posting to anime channel
**Solution:**
- Verify `WORLD_NEWS_CHANNEL_ID` is set in GitHub Secrets
- Check logs for "Routing X to WORLD_NEWS_CHANNEL"
- Ensure source is in `WORLD_NEWS_SOURCES` set

### Issue 2: Duplicate posts appearing
**Solution:**
- Check database connection: Look for "Supabase connected successfully"
- Verify `posted_news` table exists and has indexes
- Check logs for "Loaded X titles from last 7 days"

### Issue 3: Old news posting
**Solution:**
- Verify news items have `publish_date` set
- Check `is_today_or_yesterday()` function is being called
- Set `DEBUG_MODE=False` in production

### Issue 4: Database connection failures
**Solution:**
- Verify `SUPABASE_URL` and `SUPABASE_KEY` are correct
- Check Supabase project is not paused
- Review RLS policies are correctly set

## Success Indicators ✅

After 24 hours, you should see:
- [x] 6 successful runs (every 4 hours)
- [x] Posts distributed across correct channels
- [x] Zero duplicate posts
- [x] Only fresh news (today/yesterday)
- [x] Admin reports showing correct stats
- [x] No errors in GitHub Actions logs

## Key Differences from Old Version

| Feature | Old Version | Fixed Version |
|---------|-------------|---------------|
| Channel Routing | ❌ Mixed/broken | ✅ Strict source-to-channel mapping |
| DC News Channel | ⚠️ Separate | ✅ Merged with anime news |
| Spam Detection | ⚠️ Basic | ✅ Triple-layer (exact/fuzzy/DB) |
| Date Filtering | ⚠️ Weak | ✅ Strict (today/yesterday only) |
| World News Format | ❌ Same as anime | ✅ Special HTML format |
| Database Tracking | ⚠️ Basic | ✅ Strong with status tracking |
| Midnight Reset | ❌ None | ✅ Automatic new day detection |

## Emergency Contacts

If critical issues arise:
1. Check GitHub Actions logs first
2. Review admin Telegram reports
3. Check Supabase dashboard
4. Refer to `README.md` for detailed info

## Final Verification Checklist

Before marking deployment complete:
- [ ] All environment variables set
- [ ] Database schema updated
- [ ] Test run completed successfully
- [ ] First automated run verified
- [ ] Correct channel routing confirmed
- [ ] No duplicates observed
- [ ] Admin reports working
- [ ] Backup created
- [ ] Rollback plan documented

---

**Deployment Date:** _______________
**Deployed By:** _______________
**Status:** ⚪ Pending | ✅ Complete | ❌ Rolled Back

**Notes:**
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________