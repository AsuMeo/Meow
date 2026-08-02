import os
import re
import logging
import yt_dlp
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CallbackQueryHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

YOUTUBE_PATTERN = re.compile(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+')


def download_youtube(url, format_type):
    """Скачивает видео или аудио с YouTube"""
    if format_type == "360p":
        ydl_opts = {
            'format': 'best[height<=360]',
            'outtmpl': '/app/video_%(id)s.%(ext)s',
            'max_filesize': 50 * 1024 * 1024,  # 50MB лимит Telegram
        }
    else:  # mp3
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': '/app/audio_%(id)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'max_filesize': 50 * 1024 * 1024,
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

        # Для mp3 меняем расширение
        if format_type == "mp3":
            filename = filename.rsplit('.', 1)[0] + '.mp3'

        return filename, info.get('title', 'Unknown')


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ссылку на YouTube"""
    message = update.message
    if not message or not message.text:
        return

    url = message.text.strip()
    if not YOUTUBE_PATTERN.match(url):
        return

    # Кнопки выбора
    keyboard = [
        [
            InlineKeyboardButton("📹 Видео 360p", callback_data=f"video|{url}"),
            InlineKeyboardButton("🎵 Аудио MP3", callback_data=f"mp3|{url}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await message.reply_text("Выбери формат:", reply_markup=reply_markup)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор формата"""
    query = update.callback_query
    await query.answer()

    data = query.data
    format_type, url = data.split('|', 1)

    # Удаляем кнопки
    await query.edit_message_text("⏳ Скачиваю...")

    try:
        filename, title = download_youtube(url, format_type)
        file_size = os.path.getsize(filename)

        # Проверяем размер
        if file_size > 50 * 1024 * 1024:
            # Больше 50MB — отправляем как документ (Telegram позволяет до 2GB для премиум, но бот API 50MB)
            # Или загружаем на файлообменник
            await query.edit_message_text(
                "❌ Файл слишком большой (>50MB).\n"
                "Telegram Bot API ограничивает размер.\n"
                "Попробуй скачать сам: " + url
            )
            os.remove(filename)
            return

        # Отправляем файл
        with open(filename, 'rb') as f:
            if format_type == "360p":
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=f,
                    caption=title,
                    supports_streaming=True
                )
            else:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=f,
                    title=title,
                    performer="YouTube"
                )

        await query.edit_message_text("✅ Готово!")
        os.remove(filename)

    except Exception as e:
        logger.error("Download error: " + str(e))
        await query.edit_message_text("❌ Ошибка: " + str(e))


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error: " + str(context.error))


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found!")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_error_handler(error_handler)

    logger.info("YouTube bot started!")
    application.run_polling()


if __name__ == "__main__":
    main()
