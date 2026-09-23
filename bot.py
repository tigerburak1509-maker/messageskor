import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
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

# ============================================================
# TELEGRAM BOT TOKEN
# ============================================================

BOT_TOKEN = "8383789007:AAF4U2lzfnVAS0bb4Q69gW0LRTaADQvKzQY"


# ============================================================
# RAILWAY POSTGRESQL
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL")


# ============================================================
# TÜRKİYE SAATİ
# ============================================================

TURKEY_TZ = ZoneInfo("Europe/Istanbul")


# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("telegram-mesaj-botu")


# ============================================================
# DATABASE POOL
# ============================================================

db_pool = None


# ============================================================
# DATABASE BAĞLANTISI
# ============================================================

async def connect_database():
    global db_pool

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL bulunamadı!\n"
            "Railway Variables bölümünde PostgreSQL "
            "DATABASE_URL referansını ekle."
        )

    try:
        db_pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1,
            max_size=10,
            command_timeout=60,
        )

        async with db_pool.acquire() as connection:
            await connection.fetchval("SELECT 1")

        logger.info("✅ PostgreSQL bağlantısı başarılı.")

    except Exception:
        logger.exception(
            "❌ PostgreSQL bağlantısı kurulamadı."
        )
        raise


# ============================================================
# TABLOLARI OLUŞTUR
# ============================================================

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
            CREATE INDEX IF NOT EXISTS
            idx_messages_chat_user_date
            ON messages(chat_id, user_id, message_date);
        """)

        await connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_messages_chat_date
            ON messages(chat_id, message_date);
        """)

    logger.info("✅ Database tabloları hazır.")


# ============================================================
# TÜRKİYE SAATİ
# ============================================================

def turkey_now():

    return datetime.now(
        timezone.utc
    ).astimezone(
        TURKEY_TZ
    )


# ============================================================
# GÜN BAŞLANGICI
# ============================================================

def get_day_start():

    now = turkey_now()

    return now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )


# ============================================================
# HAFTA BAŞLANGICI - PAZARTESİ
# ============================================================

def get_week_start():

    now = turkey_now()

    day_start = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    return day_start - timedelta(
        days=day_start.weekday()
    )


# ============================================================
# AY BAŞLANGICI
# ============================================================

def get_month_start():

    now = turkey_now()

    return now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )


# ============================================================
# MESAJI DATABASE'E KAYDET
# ============================================================

async def save_message(update: Update, context=None):

    if not update.message:
        return

    message = update.message
    user = message.from_user
    chat = message.chat

    if not user or not chat:
        return

    # Sadece grup ve süpergruplar
    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    # Bot mesajlarını sayma
    if user.is_bot:
        return

    try:

        message_date = message.date

        if message_date.tzinfo is None:
            message_date = message_date.replace(
                tzinfo=timezone.utc
            )

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
                message_date
            )

    except Exception:

        logger.exception(
            "Mesaj kaydedilirken hata oluştu."
        )


# ============================================================
# KULLANICI MESAJ SAYISI
# ============================================================

async def get_user_count(
    chat_id,
    user_id,
    start_date=None
):

    async with db_pool.acquire() as connection:

        if start_date:

            count = await connection.fetchval(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE chat_id = $1
                  AND user_id = $2
                  AND message_date >= $3
                """,
                chat_id,
                user_id,
                start_date
            )

        else:

            count = await connection.fetchval(
                """
                SELECT COUNT(*)
                FROM messages
                WHERE chat_id = $1
                  AND user_id = $2
                """,
                chat_id,
                user_id
            )

    return count or 0


# ============================================================
# /mesajim
# ============================================================

async def command_mesajim(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        await update.message.reply_text(
            "❌ Bu komut sadece gruplarda kullanılabilir."
        )
        return

    daily = await get_user_count(
        chat.id,
        user.id,
        get_day_start()
    )

    weekly = await get_user_count(
        chat.id,
        user.id,
        get_week_start()
    )

    monthly = await get_user_count(
        chat.id,
        user.id,
        get_month_start()
    )

    total = await get_user_count(
        chat.id,
        user.id
    )

    name = user.first_name or "Kullanıcı"

    await update.message.reply_text(
        f"📊 <b>{name}</b>\n\n"
        f"📅 Bugün: <b>{daily:,}</b>\n"
        f"📆 Bu hafta: <b>{weekly:,}</b>\n"
        f"🗓 Bu ay: <b>{monthly:,}</b>\n"
        f"💬 Toplam: <b>{total:,}</b>",
        parse_mode="HTML"
    )


# ============================================================
# /gunluk
# ============================================================

async def command_gunluk(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    count = await get_user_count(
        chat.id,
        user.id,
        get_day_start()
    )

    name = user.first_name or "Kullanıcı"

    await update.message.reply_text(
        f"📅 <b>{name}</b>\n\n"
        f"Bugün <b>{count:,}</b> mesaj gönderdin.",
        parse_mode="HTML"
    )


# ============================================================
# /haftalik
# ============================================================

async def command_haftalik(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    count = await get_user_count(
        chat.id,
        user.id,
        get_week_start()
    )

    name = user.first_name or "Kullanıcı"

    await update.message.reply_text(
        f"📆 <b>{name}</b>\n\n"
        f"Bu hafta <b>{count:,}</b> mesaj gönderdin.",
        parse_mode="HTML"
    )


# ============================================================
# /aylik
# ============================================================

async def command_aylik(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    count = await get_user_count(
        chat.id,
        user.id,
        get_month_start()
    )

    name = user.first_name or "Kullanıcı"

    await update.message.reply_text(
        f"🗓 <b>{name}</b>\n\n"
        f"Bu ay <b>{count:,}</b> mesaj gönderdin.",
        parse_mode="HTML"
    )


# ============================================================
# /toplam
# ============================================================

async def command_toplam(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    chat = update.effective_chat

    if not chat:
        return

    if chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP
    ):
        return

    async with db_pool.acquire() as connection:

        users = await connection.fetch(
            """
            SELECT
                user_id,
                MAX(first_name) AS first_name,
                MAX(last_name) AS last_name,
                MAX(username) AS username,
                COUNT(*) AS total
            FROM messages
            WHERE chat_id = $1
            GROUP BY user_id
            ORDER BY total DESC
            LIMIT 100
            """,
            chat.id
        )

        total_messages = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM messages
            WHERE chat_id = $1
            """,
            chat.id
        )

    if not users:

        await update.message.reply_text(
            "📊 Henüz kayıtlı mesaj bulunmuyor."
        )

        return

    lines = []

    for number, row in enumerate(
        users,
        start=1
    ):

        first_name = row["first_name"] or "İsimsiz"
        last_name = row["last_name"] or ""

        name = f"{first_name} {last_name}".strip()

        username = row["username"]

        if username:
            name = f"{name} (@{username})"

        count = row["total"]

        lines.append(
            f"<b>{number}.</b> {name} — "
            f"<b>{count:,}</b>"
        )

    text = (
        "🏆 <b>GRUP MESAJ İSTATİSTİĞİ</b>\n\n"
        + "\n".join(lines)
        + f"\n\n💬 <b>Toplam mesaj:</b> "
        f"{total_messages:,}"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# ============================================================
# /yardim
# ============================================================

async def command_yardim(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    await update.message.reply_text(
        "🤖 <b>Telegram Mesaj Botu</b>\n\n"
        "📊 /mesajim\n"
        "Kendi günlük, haftalık, aylık ve toplam mesajını gösterir.\n\n"
        "📅 /gunluk\n"
        "Bugünkü mesajını gösterir.\n\n"
        "📆 /haftalik\n"
        "Bu haftaki mesajını gösterir.\n\n"
        "🗓 /aylik\n"
        "Bu ayki mesajını gösterir.\n\n"
        "🏆 /toplam\n"
        "Gruptaki kullanıcıların toplam mesajlarını gösterir.\n\n"
        "ℹ️ Tüm kullanıcılar ve yöneticiler sayılır.",
        parse_mode="HTML"
    )


# ============================================================
# HATA YÖNETİMİ
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Telegram hatası: %s",
        context.error
    )


# ============================================================
# BOT
# ============================================================

async def main():

    logger.info(
        "Telegram Mesaj Botu başlatılıyor..."
    )

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN bulunamadı!"
        )

    # PostgreSQL bağlantısı
    await connect_database()

    # Tablolar
    await create_database()

    # Telegram
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # ========================================================
    # KOMUTLAR
    # ========================================================

    application.add_handler(
        CommandHandler(
            "mesajim",
            command_mesajim
        )
    )

    application.add_handler(
        CommandHandler(
            "gunluk",
            command_gunluk
        )
    )

    application.add_handler(
        CommandHandler(
            "haftalik",
            command_haftalik
        )
    )

    application.add_handler(
        CommandHandler(
            "aylik",
            command_aylik
        )
    )

    application.add_handler(
        CommandHandler(
            "toplam",
            command_toplam
        )
    )

    application.add_handler(
        CommandHandler(
            "yardim",
            command_yardim
        )
    )

    # ========================================================
    # NORMAL MESAJLAR
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            save_message
        )
    )

    application.add_error_handler(
        error_handler
    )

    # ========================================================
    # BAŞLAT
    # ========================================================

    await application.initialize()

    await application.start()

    await application.updater.start_polling(
        allowed_updates=Update.ALL_TYPES
    )

    logger.info(
        "✅ BOT AKTİF. Mesajlar sayılıyor."
    )

    try:

        while True:
            await asyncio.sleep(3600)

    except asyncio.CancelledError:

        pass

    finally:

        await application.updater.stop()

        await application.stop()

        await application.shutdown()

        if db_pool:
            await db_pool.close()


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info(
            "Bot kapatıldı."
        )
