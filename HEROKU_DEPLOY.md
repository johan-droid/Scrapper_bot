# Deploying Scrapper Bot to Heroku

This bot is configured to be easily deployed to Heroku.

## Prerequisites

- A Heroku account
- [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli) installed (optional, for manual deployment)
- A Supabase project (for database)
- Telegram Bot Token and Channel IDs

## Option 1: One-Click Deployment (Recommended)

Since `app.json` is configured, you can use the "Deploy to Heroku" button if this repo is hosted on GitHub.

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy)

(Note: This button works when viewing the repository on GitHub).

## Option 2: Manual Deployment via CLI

1.  **Login to Heroku**:
    ```bash
    heroku login
    ```

2.  **Create a new Heroku app**:
    ```bash
    heroku create your-app-name
    ```

3.  **Add the Postgres addon (optional, if you aren't using Supabase but need a DB, though this bot is setup for Supabase)**.
    *This bot uses Supabase, so you just need to set the environment variables.*

4.  **Set Environment Variables**:
    Replace the values with your actual credentials.

    ```bash
    heroku config:set BOT_TOKEN="your_token"
    heroku config:set CHAT_ID="your_chat_id"
    heroku config:set REDDIT_CHANNEL_ID="-100..."
    heroku config:set ANIME_NEWS_CHANNEL_ID="-100..."
    heroku config:set WORLD_NEWS_CHANNEL_ID="-100..."
    heroku config:set ADMIN_ID="your_id"
    heroku config:set SUPABASE_URL="your_supabase_url"
    heroku config:set SUPABASE_KEY="your_supabase_key"
    ```

5.  **Deploy**:
    ```bash
    git push heroku main
    ```
    (Or `git push heroku master` depending on your branch name).

6.  **Scale the Dyno**:
    Ensure the web worker is running:
    ```bash
    heroku ps:scale web=1
    ```

## Notes

- **Self-Ping**: The bot includes a self-ping mechanism to keep the free Dyno alive (if relying on uptime). On Heroku, set `HEROKU_APP_NAME` config var to your app name (e.g., `your-app-name`) so the bot knows its own URL.
- **Python Version**: The expected Python version is defined in `runtime.txt`.

## Troubleshooting

### "App not compatible with buildpack: heroku/nodejs"
If you see this error, it means your Heroku app is incorrectly configured to use Node.js instead of Python. This can happen if Heroku failed to auto-detect the language or if it was previously set to Node.js.

To fix this, run the following commands in your terminal:

```bash
# Clear existing buildpacks
heroku buildpacks:clear

# Set the buildpack to Python
heroku buildpacks:set heroku/python

# Verify the buildpack
heroku buildpacks
```

Then push your code again:
```bash
git push heroku main
```
