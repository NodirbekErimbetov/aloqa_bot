import logging
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand, ReplyKeyboardRemove, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "bot.db"


def welcome_text(user) -> str:
    # Telegramdagi ismi (first_name + last_name)
    name = user.full_name or user.first_name or "foydalanuvchi"
    return (
        f"Assalomu alaykum, {name}!\n"
        "Murojaatingizni yo'llashingiz mumkin."
    )


def get_admin_id() -> int | None:
    raw = os.getenv("ADMIN_ID", "").strip()
    if not raw:
        return None
    return int(raw)


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS message_map (
                admin_message_id INTEGER PRIMARY KEY,
                user_chat_id INTEGER NOT NULL
            )
            """
        )


def save_mapping(admin_message_id: int, user_chat_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO message_map (admin_message_id, user_chat_id) VALUES (?, ?)",
            (admin_message_id, user_chat_id),
        )


def get_user_chat_id(admin_message_id: int) -> int | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT user_chat_id FROM message_map WHERE admin_message_id = ?",
            (admin_message_id,),
        ).fetchone()
    return row[0] if row else None


def user_info(user) -> str:
    parts = []
    if user.full_name:
        parts.append(user.full_name)
    if user.username:
        parts.append(f"@{user.username}")
    parts.append(f"ID: {user.id}")
    return " | ".join(parts)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start: salomlashish faqat userga. Admin ga hech narsa yuborilmaydi."""
    admin_id = get_admin_id()
    user = update.effective_user

    # Admin Start bossa — Assalomu matni chiqmasin (u faqat userlar uchun)
    if admin_id and user.id == admin_id:
        return

    await update.message.reply_text(
        welcome_text(user),
        reply_markup=ReplyKeyboardRemove(),
    )


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start dan keyin user yozgan xabar faqat adminga (bot chatiga) keladi."""
    admin_id = get_admin_id()
    if not admin_id:
        await update.message.reply_text(
            "Bot hali sozlanmagan. ADMIN_ID ni .env faylga yozing."
        )
        return

    user = update.effective_user
    message = update.message

    # Start buyrug'i yoki bo'sh xabar adminga ketmasin
    if not message or (message.text and message.text.startswith("/")):
        return

    header = f"📩 Yangi xabar\n👤 {user_info(user)}\n\n"

    try:
        if message.text:
            sent = await context.bot.send_message(
                chat_id=admin_id,
                text=header + message.text,
            )
            save_mapping(sent.message_id, user.id)
        else:
            header_msg = await context.bot.send_message(
                chat_id=admin_id,
                text=header.strip(),
            )
            await message.copy(
                chat_id=admin_id,
                reply_to_message_id=header_msg.message_id,
            )
            save_mapping(header_msg.message_id, user.id)

        # Tasdiq faqat userga
        await message.reply_text(
            "Murojaatingiz adminga yuborildi. "
            "Admin tez orada javob beradi."
        )
    except Exception:
        logger.exception("Foydalanuvchi xabarini admin'ga yuborishda xato")
        await message.reply_text("Xatolik yuz berdi. Keyinroq qayta urinib ko'ring.")


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = get_admin_id()
    message = update.message

    if not admin_id or message.from_user.id != admin_id:
        return

    if not message.reply_to_message:
        return

    user_chat_id = get_user_chat_id(message.reply_to_message.message_id)
    if not user_chat_id:
        await message.reply_text(
            "Bu xabarga javob berib bo'lmaydi. Foydalanuvchi xabariga reply qiling."
        )
        return

    try:
        if message.text:
            await context.bot.send_message(chat_id=user_chat_id, text=message.text)
        else:
            await message.copy(chat_id=user_chat_id)
        await message.reply_text("✅ Javob yuborildi.")
    except Exception:
        logger.exception("Admin javobini foydalanuvchiga yuborishda xato")
        await message.reply_text("Javob yuborilmadi. Foydalanuvchi botni bloklagan bo'lishi mumkin.")


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(f"Sizning Telegram ID: `{user.id}`", parse_mode=ParseMode.MARKDOWN)


async def on_startup(app: Application) -> None:
    await app.bot.set_my_commands([BotCommand("start", "Botni boshlash")])


def build_application() -> Application:
    """Bot application yaratish (hosting va lokal uchun)."""
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN topilmadi. Environment Variables ni tekshiring.")

    admin_id = get_admin_id()
    if not admin_id:
        logger.warning("ADMIN_ID hali kiritilmagan.")

    init_db()

    builder = (
        Application.builder()
        .token(token)
        .post_init(on_startup)
        # Sekin internet uchun kutish vaqtini oshiramiz
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(40)
    )
    # Agar Telegram bloklangan bo'lsa, .env ga PROXY_URL yozish mumkin
    # Masalan: PROXY_URL=socks5://127.0.0.1:1080 yoki http://127.0.0.1:8080
    proxy = os.getenv("PROXY_URL", "").strip()
    if proxy:
        builder = builder.proxy(proxy).get_updates_proxy(proxy)
        logger.info("Proxy orqali ulanilmoqda: %s", proxy)
    app = builder.build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("my_id", my_id))

    if admin_id:
        app.add_handler(
            MessageHandler(
                filters.User(user_id=admin_id) & filters.REPLY,
                handle_admin_reply,
            )
        )
        user_filter = filters.ALL & ~filters.COMMAND & ~filters.User(user_id=admin_id)
    else:
        user_filter = filters.ALL & ~filters.COMMAND

    app.add_handler(MessageHandler(user_filter, handle_user_message))
    return app


def main() -> None:
    logger.info("Bot polling rejimida ishga tushdi...")
    # bootstrap_retries=-1: internet uzilsa ham to'xtamay qayta urinadi
    build_application().run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=-1,
    )


if __name__ == "__main__":
    main()
