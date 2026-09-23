import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# AYARLAR
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

TURKEY_TZ = ZoneInfo("Europe/Istanbul")

ALLOWED_GROUPS = {
    "heroprimesohbet",
    "testkanaliii00",
}

db_pool = None

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("mesajbot")


# =========================================================
# GRUP KONTROLÜ
# =========================================================

def is_allowed_group(update: Update) -> bool:
    message = update.effective_message
    chat = update.effective_chat

    if not message or not chat:
        return False

    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return False

    username = (chat.username or "").lower().lstrip("@")

    return username in ALLOWED_GROUPS


# =========================================================
# DATABASE
# =========================================================

async def connect_database():
    global db_pool

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL bulunamadı!")

    logger.info("PostgreSQL bağlantısı başlatılıyor...")

    db_pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=1,
        max_size=10,
        command_timeout=60,
    )

    async with db_pool.acquire() as connection:
        await connection.fetchval("SELECT 1")

    logger.info("✅ PostgreSQL bağlantısı başarılı.")


async def create_database():
    async with db_pool.acquire() as connection:

        await connection.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id BIGSERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                message_date TIMESTAMPTZ NOT NULL
            );
        """)

        await connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_chat_user_date
            ON messages(chat_id, user_id, message_date);
        """)

        await connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_chat_date
            ON messages(chat_id, message_date);
        """)

    logger.info("✅ Database tabloları hazır.")


# =========================================================
# TÜRKİYE SAATİ
# =========================================================

def turkey_now():
    return datetime.now(TURKEY_TZ)


def get_day_start():
    now = turkey_now()

    return now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def get_week_start():
    today = get_day_start()

    return today - timedelta(days=today.weekday())


def get_month_start():
    now = turkey_now()

    return now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


# =========================================================
# MESAJ KAYDETME
# =========================================================

async def save_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user:
        return

    logger.info(
        "📩 UPDATE ALINDI | chat_id=%s | chat_type=%s | username=%s | user=%s | text=%r",
        chat.id,
        chat.type,
        chat.username,
        user.username,
        message.text,
    )

    # Özel sohbetlerde mesajları sadece debug için görüyoruz.
    if chat.type == ChatType.PRIVATE:
        logger.info("ℹ️ Özel sohbet mesajı alındı.")
        return

    # Sadece grup/süpergrup
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    # Sadece izin verilen iki grup
    if not is_allowed_group(update):
        logger.info(
            "🚫 İzin verilmeyen grup: %s (%s)",
            chat.title,
            chat.username,
        )
        return

    # Bot mesajlarını sayma
    if user.is_bot:
        return

    message_date = message.date

    async with db_pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO messages (
                chat_id,
                user_id,
                username,
                first_name,
                last_name,
                message_date
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            chat.id,
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            message_date,
        )

    logger.info(
        "💾 MESAJ KAYDEDİLDİ | grup=%s | kullanıcı=%s",
        chat.username,
        user.username or user.first_name,
    )


# =========================================================
# SAYIM
# =========================================================

async def get_user_count(chat_id, user_id, start_date=None):

    if start_date:
        query = """
            SELECT COUNT(*)
            FROM messages
            WHERE chat_id = $1
              AND user_id = $2
              AND message_date >= $3
        """

        async with db_pool.acquire() as connection:
            return await connection.fetchval(
                query,
                chat_id,
                user_id,
                start_date,
            )

    query = """
        SELECT COUNT(*)
        FROM messages
        WHERE chat_id = $1
          AND user_id = $2
    """

    async with db_pool.acquire() as connection:
        return await connection.fetchval(
            query,
            chat_id,
            user_id,
        )


# =========================================================
# /MESAJIM
# =========================================================

async def mesajim(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user:
        return

    logger.info(
        "🟢 /mesajim çalıştı | chat=%s | user=%s",
        chat.id,
        user.id,
    )

    if chat.type == ChatType.PRIVATE:
        await message.reply_text(
            "✅ Bot çalışıyor.\n\n"
            "Bu bot mesaj sayımını sadece izin verilen gruplarda yapar."
        )
        return

    if not is_allowed_group(update):
        return

    count = await get_user_count(chat.id, user.id)

    await message.reply_text(
        f"📊 {user.first_name}\n\n"
        f"Toplam mesajınız: {count}"
    )


# =========================================================
# /GUNLUK
# =========================================================

async def gunluk(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_allowed_group(update):
        return

    user = update.effective_user
    chat = update.effective_chat

    count = await get_user_count(
        chat.id,
        user.id,
        get_day_start(),
    )

    await update.effective_message.reply_text(
        f"📅 Bugünkü mesajınız: {count}"
    )


# =========================================================
# /HAFTALIK
# =========================================================

async def haftalik(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_allowed_group(update):
        return

    user = update.effective_user
    chat = update.effective_chat

    count = await get_user_count(
        chat.id,
        user.id,
        get_week_start(),
    )

    await update.effective_message.reply_text(
        f"📅 Bu haftaki mesajınız: {count}"
    )


# =========================================================
# /AYLIK
# =========================================================

async def aylik(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_allowed_group(update):
        return

    user = update.effective_user
    chat = update.effective_chat

    count = await get_user_count(
        chat.id,
        user.id,
        get_month_start(),
    )

    await update.effective_message.reply_text(
        f"📅 Bu ayki mesajınız: {count}"
    )


# =========================================================
# /TOPLAM
# =========================================================

async def toplam(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_allowed_group(update):
        return

    chat = update.effective_chat

    async with db_pool.acquire() as connection:

        rows = await connection.fetch(
            """
            SELECT
                user_id,
                username,
                first_name,
                last_name,
                COUNT(*) AS total
            FROM messages
            WHERE chat_id = $1
            GROUP BY
                user_id,
                username,
                first_name,
                last_name
            ORDER BY total DESC
            LIMIT 20
            """,
            chat.id,
        )

    if not rows:
        await update.effective_message.reply_text(
            "Henüz kayıtlı mesaj bulunmuyor."
        )
        return

    lines = ["🏆 TOPLAM MESAJ SIRALAMASI", ""]

    for index, row in enumerate(rows, start=1):

        name = (
            f"@{row['username']}"
            if row["username"]
            else row["first_name"] or "Kullanıcı"
        )

        lines.append(
            f"{index}. {name} — {row['total']} mesaj"
        )

    await update.effective_message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# /YARDIM
# =========================================================

async def yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.effective_message.reply_text(
        "🤖 MESAJ SAYMA BOTU\n\n"
        "/mesajim - Toplam mesajınız\n"
        "/gunluk - Bugünkü mesajınız\n"
        "/haftalik - Haftalık mesajınız\n"
        "/aylik - Aylık mesajınız\n"
        "/toplam - Grup sıralaması\n"
        "/yardim - Yardım"
    )


# =========================================================
# HATA
# =========================================================

async def error_handler(update, context):

    logger.error(
        "❌ TELEGRAM HATASI: %s",
        context.error,
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

async def main():

    logger.info("========================================")
    logger.info("🚀 TELEGRAM MESAJ BOTU BAŞLATILIYOR")
    logger.info("========================================")

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN Railway Variables içinde bulunamadı!"
        )

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL Railway Variables içinde bulunamadı!"
        )

    # DATABASE
    await connect_database()
    await create_database()

    # TELEGRAM
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Komutlar
    application.add_handler(
        CommandHandler("mesajim", mesajim)
    )

    application.add_handler(
        CommandHandler("gunluk", gunluk)
    )

    application.add_handler(
        CommandHandler("haftalik", haftalik)
    )

    application.add_handler(
        CommandHandler("aylik", aylik)
    )

    application.add_handler(
        CommandHandler("toplam", toplam)
    )

    application.add_handler(
        CommandHandler("yardim", yardim)
    )

    # Normal mesajlar
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            save_message,
        )
    )

    application.add_error_handler(error_handler)

    # Telegram bağlantısı
    await application.initialize()

    bot_info = await application.bot.get_me()

    logger.info(
        "🤖 BOT: @%s | id=%s",
        bot_info.username,
        bot_info.id,
    )

    logger.info(
        "📡 can_read_all_group_messages=%s",
        bot_info.can_read_all_group_messages,
    )

    # Webhook varsa temizle
    await application.bot.delete_webhook(
        drop_pending_updates=False
    )

    await application.start()

    # SADECE message + my_chat_member
    await application.updater.start_polling(
        allowed_updates=[
            "message",
            "my_chat_member",
        ],
        drop_pending_updates=False,
    )

    logger.info("========================================")
    logger.info("✅ BOT AKTİF")
    logger.info("📊 Mesajlar sayılıyor.")
    logger.info("🔒 İzin verilen gruplar:")
    logger.info("   @heroprimesohbet")
    logger.info("   @testkanaliii00")
    logger.info("========================================")

    try:
        while True:
            await asyncio.sleep(3600)

    finally:

        await application.updater.stop()
        await application.stop()
        await application.shutdown()

        if db_pool:
            await db_pool.close()


if __name__ == "__main__":
    asyncio.run(main())
