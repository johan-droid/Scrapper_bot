-- Command to reset posts for a specific date (e.g., today) to allow the bot to repost them.
-- WARNING: This will delete the record of these posts being sent. 
-- Only run this if the posts FAILED to send to Telegram but were recorded in the database.

-- Replace '2026-02-03' with the date you want to reset (YYYY-MM-DD)
DELETE FROM posted_news 
WHERE posted_date = '2026-02-03';

-- Validated that table is 'posted_news' and column is 'posted_date' from src/database.py
