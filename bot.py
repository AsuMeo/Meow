import os
import io
import logging
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from telegram import Update, InputSticker, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, MessageHandler, filters, ContextTypes, ChatMemberHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Храним связь: message_id поста канала -> message_id обсуждения
channel_posts = {}

def create_sticker_image(name, text, avatar_url=None):
    """Создаёт изображение стикера с именем, текстом и аватаркой"""
    width, height = 512, 256

    # Фон — градиент
    img = Image.new('RGB', (width, height), '#1a1a2e')
    draw = ImageDraw.Draw(img)

    # Загружаем аватарку или делаем круг с инициалами
    avatar_size = 80
    avatar_x, avatar_y = 20, 20

    if avatar_url:
        try:
            resp = requests.get(avatar_url, timeout=10)
            avatar = Image.open(io.BytesIO(resp.content)).convert('RGBA')
            avatar = avatar.resize((avatar_size, avatar_size))
            # Круглая маска
            mask = Image.new('L', (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
            img.paste(avatar, (avatar_x, avatar_y), mask)
        except:
            avatar_url = None

    if not avatar_url:
        # Круг с цветом
        draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size), fill='#e94560')
        initial = name[0].upper() if name else '?'
        try:
            font_init = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
        except:
            font_init = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), initial, font=font_init)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text((avatar_x + (avatar_size - text_w)//2, avatar_y + (avatar_size - text_h)//2 - 5), 
                  initial, fill='white', font=font_init)

    # Имя
    try:
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except:
        font_name = ImageFont.load_default()
        font_text = ImageFont.load_default()

    draw.text((avatar_x + avatar_size + 15, avatar_y + 5), name, fill='#e94560', font=font_name)

    # Текст комментария — перенос строк
    max_width = width - avatar_x - avatar_size - 30
    lines = []
    words = text.split()
    current_line = ""
    for word in words:
        test = current_line + " " + word if current_line else word
        bbox = draw.textbbox((0, 0), test, font=font_text)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    # Обрезаем если слишком много строк
    lines = lines[:6]
    if len(text.split()) > sum(len(l.split()) for l in lines):
        lines[-1] = lines[-1][:30] + "..."

    y_offset = avatar_y + 40
    for line in lines:
        draw.text((avatar_x + avatar_size + 15, y_offset), line, fill='white', font=font_text)
        y_offset += 28

    # Рамка
    draw.rectangle((0, 0, width-1, height-1), outline='#e94560', width=3)

    # Конвертируем в webp для стикера
    webp_buffer = io.BytesIO()
    img.save(webp_buffer, format='WEBP')
    webp_buffer.seek(0)

    return webp_buffer

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запоминаем посты канала"""
    if update.channel_post:
        post = update.channel_post
        # Если у поста есть обсуждение — сохраняем связь
        if post.chat.linked_chat_id:
            channel_posts[post.message_id] = {
                'chat_id': post.chat.linked_chat_id,
                'channel_id': post.chat.id
            }
            logger.info(f"Пост {post.message_id} связан с чатом {post.chat.linked_chat_id}")

async def handle_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает комментарии в чате обсуждения"""
    message = update.message
    if not message:
        return

    # Пропускаем сообщения от самого бота
    if message.from_user and message.from_user.is_bot:
        return

    # Получаем данные автора
    user = message.from_user
    name = user.full_name or user.username or "Аноним"
    text = message.text or message.caption or ""

    # Получаем аватарку
    avatar_url = None
    try:
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if photos.photos:
            file = await context.bot.get_file(photos.photos[0][-1].file_id)
            avatar_url = file.file_path
    except:
        pass

    # Создаём изображение стикера
    sticker_img = create_sticker_image(name, text, avatar_url)

    # Удаляем оригинальное сообщение
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Не удалось удалить: {e}")

    # Отправляем как фото (стикер-формат webp отправляем как фото — Telegram покажет как изображение)
    # Или как документ/стикер
    try:
        # Отправляем как фото в чат обсуждения
        await context.bot.send_photo(
            chat_id=message.chat_id,
            photo=sticker_img,
            reply_to_message_id=message.reply_to_message.message_id if message.reply_to_message else None
        )
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        # Fallback — отправляем текстом
        await context.bot.send_message(
            chat_id=message.chat_id,
            text=f"💬 {name}:
{text}",
            reply_to_message_id=message.reply_to_message.message_id if message.reply_to_message else None
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не найден!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Отслеживаем посты канала
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, handle_channel_post))

    # Отслеживаем комментарии в чатах
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, handle_comment))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.GROUPS, handle_comment))

    application.add_error_handler(error_handler)

    logger.info("Анонимный бот запущен!")
    application.run_polling()

if __name__ == "__main__":
    main()
