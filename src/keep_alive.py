import logging
import os
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return {
        "status": "online",
        "service": "Scrapper Bot",
        "schedule": "Every 2 hours",
        "mode": "Optimized Worker (Heroku 1x)",
        "message": "Runner is awake and active."
    }, 200

@app.route('/health')
def health():
    return "OK", 200

def run():
    # Only run web server if not in Heroku worker mode
    if not os.getenv('HEROKU_WORKER_MODE'):
        app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
