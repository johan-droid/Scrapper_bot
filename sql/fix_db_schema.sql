-- Fix missing columns for Telegraph Edition
-- Run this in Supabase SQL Editor

DO $$ 
BEGIN 
    -- 1. Add article_url if missing (Original source URL)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='posted_news' AND column_name='article_url') THEN
        ALTER TABLE posted_news ADD COLUMN article_url TEXT;
        RAISE NOTICE 'Added article_url column';
    END IF;

    -- 2. Add telegraph_url if missing (Telegraph page URL)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='posted_news' AND column_name='telegraph_url') THEN
        ALTER TABLE posted_news ADD COLUMN telegraph_url TEXT;
        RAISE NOTICE 'Added telegraph_url column';
    END IF;

    -- 3. Reload schema cache (Important for PostgREST)
    NOTIFY pgrst, 'reload config';
END $$;
