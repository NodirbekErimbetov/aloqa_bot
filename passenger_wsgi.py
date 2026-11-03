"""Hostmaster / cPanel WSGI kirish nuqtasi (webhook rejimi)."""

import asyncio
import logging
import os
import traceback
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook").strip() or "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

flask_app = Flask(__name__)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
ptb_app = None
startup_error = ""
webhook_ready = False


def get_ptb_app():
    global ptb_app
    if ptb_app is not None:
        return ptb_app

    from bot import build_application

    ptb_app = build_application()
    return ptb_app


def setup_webhook() -> None:
    global startup_error, webhook_ready

    if not BOT_TOKEN:
        startup_error = "BOT_TOKEN yo'q. cPanel Environment Variables ga qo'shing."
        return

    if not WEBHOOK_URL:
        startup_error = "WEBHOOK_URL yo'q. Masalan: https://bot.attezkor.uz/webhook"
        return

    try:
        app = get_ptb_app()
        loop.run_until_complete(app.initialize())
        loop.run_until_complete(app.start())
        loop.run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))
        loop.run_until_complete(app.bot.set_webhook(url=WEBHOOK_URL))
        webhook_ready = True
        logger.info("Webhook o'rnatildi: %s", WEBHOOK_URL)
    except Exception:
        startup_error = traceback.format_exc()
        logger.exception("Webhook sozlashda xato")


@flask_app.route("/", methods=["GET"])
def index():
    if startup_error:
        return f"Xato:\n{startup_error}", 500
    if not webhook_ready:
        return "Bot yuklandi, webhook hali tayyor emas", 200
    return "Aloqa bot ishlayapti", 200


@flask_app.route("/status", methods=["GET"])
def status():
    checks = {
        "bot_token": bool(BOT_TOKEN),
        "webhook_url": WEBHOOK_URL or "YO'Q",
        "webhook_ready": webhook_ready,
        "startup_error": startup_error or "YO'Q",
    }
    return str(checks), 200


@flask_app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    from telegram import Update

    try:
        app = get_ptb_app()
        update = Update.de_json(request.get_json(force=True), app.bot)
        loop.run_until_complete(app.process_update(update))
        return "", 200
    except Exception:
        logger.exception("Webhook xatosi")
        return "", 500


try:
    setup_webhook()
except Exception:
    startup_error = traceback.format_exc()
    logger.exception("Bot ishga tushirishda xato")

application = flask_app
