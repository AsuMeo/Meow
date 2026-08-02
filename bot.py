import os
import io
import re
import logging
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Регулярка для ссылок и @упоминаний
LINK_PATTERN = re.compile(r'https?://|www\.|t\.me/|@[\w_]+')


def create_sticker_image(name, text, avatar_url=None, media_type=None):
    """Создаёт красивый стикер в стиле Telegram dark theme"""
    width, height = 512, 256

    # Градиентный фон
    img = Image.new("RGB", (width, height), "#0d1117")
    draw = ImageDraw.Draw(img)

    # Тень/свечение снизу
    for i in range(20):
        alpha = int(30 * (1 - i/20))
        draw.rectangle((0, height - 40 + i, width, height - 39 + i), fill=(228, 69, 96, alpha))

    # Аватарка
    avatar_size = 72
    avatar_x, avatar_y = 24, 24

    if avatar_url:
        try:
            resp = requests.get(avatar_url, timeout=10)
            avatar = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            avatar = avatar.resize((avatar_size, avatar_size))
            # Круглая аватарка с обводкой
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
            img.paste(avatar, (avatar_x, avatar_y), mask)
            # Обводка аватарки
            draw.ellipse((avatar_x-2, avatar_y-2, avatar_x + avatar_size+2, avatar_y + avatar_size+2), outline="#e94560", width=3)
        except:
            avatar_url = None

    if not avatar_url:
        # Градиентный круг с инициалом
        draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size), fill="#e94560")
        initial = name[0].upper() if name else "?"
        try:
            font_init = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        except:
            font_init = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), initial, font=font_init)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text((avatar_x + (avatar_size - text_w)//2, avatar_y + (avatar_size - text_h)//2 - 4), initial, fill="white", font=font_init)

    # Шрифты
    try:
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        font_media = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", 18)
    except:
        font_name = ImageFont.load_default()
        font_text = ImageFont.load_default()
        font_media = ImageFont.load_default()

    # Имя с градиентным цветом
    draw.text((avatar_x + avatar_size + 16, avatar_y + 2), name, fill="#e94560", font=font_name)

    # Пузырь сообщения — скруглённый прямоугольник
    bubble_x = avatar_x + avatar_size + 12
    bubble_y = avatar_y + 36
    bubble_w = width - bubble_x - 24
    bubble_h = height - bubble_y - 30

    # Тень пузыря
    draw.rounded_rectangle((bubble_x+2, bubble_y+2, bubble_x + bubble_w+2, bubble_y + bubble_h+2), radius=20, fill="#161b22")
    # Сам пузырь
    draw.rounded_rectangle((bubble_x, bubble_y, bubble_x + bubble_w, bubble_y + bubble_h), radius=20, fill="#21262d", outline="#30363d", width=2)

    # Текст внутри пузыря
    text_x = bubble_x + 16
    text_y = bubble_y + 14
    max_text_w = bubble_w - 32

    # Если есть медиа — показываем метку
    display_text = text
    if media_type:
        display_text = "[" + media_type + "] " + text if text else "[" + media_type + "]"
        draw.text((text_x, text_y), display_text, fill="#8b949e", font=font_media)
    else:
        # Перенос строк
        lines = []
        words = display_text.split()
        current_line = ""
        for word in words:
            test = current_line + " " + word if current_line else word
            bbox = draw.textbbox((0, 0), test, font=font_text)
            if bbox[2] - bbox[0] <= max_text_w:
                current_line = test
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        lines = lines[:5]
        if len(words) > sum(len(l.split()) for l in lines):
            lines[-1] = lines[-1][:25] + "..."

        for line in lines:
            draw.text((text_x, text_y), line, fill="#c9d1d9", font=font_text)
            text_y += 26

    # Время внизу справа
    try:
        font_time = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    except:
        font_time = ImageFont.load_default()
    draw.text((width - 70, height - 28), "now", fill="#484f58", font=font_time)

    # Рамка стикера
    draw.rounded_rectangle((2, 2, width-3, height-3), radius=8, outline="#e94560", width=3)

    # Конвертируем в PNG (Telegram принимает PNG как стикер если размеры подходят)
    # Для стикера нужен WEBP
    webp_buffer = io.BytesIO()
    img.save(webp_buffer, format="WEBP")
    webp_buffer.seek(0)
    return webp_buffer


async def check_spam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет сообщение на ссылки и @упоминания. Если спам — мутит на 1 час."""
    message = update.message
    if not message:
        return False

    text = message.text or message.caption or ""

    if LINK_PATTERN.search(text):
        try:
            await message.delete()
            # Мут на 1 час
            until_date = int(message.date.timestamp()) + 3600
            await context.bot.restrict_chat_member(
                chat_id=message.chat_id,
                user_id=message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            await context.bot.send_message(
                chat_id=message.chat_id,
                text="🚫 " + message.from_user.first_name + " получил мут на 1 час за ссылку/упоминание!"
            )
            logger.info("Muted user " + str(message.from_user.id) + " for spam")
        except Exception as e:
            logger.error("Mute error: " + str(e))
        return True
    return False


async def handle_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает комментарии в чате обсуждения"""
    message = update.message
    if not message:
        return

    if message.from_user and message.from_user.is_bot:
        return

    # Проверяем спам
    if await check_spam(update, context):
        return

    # Проверяем, что это комментарий к посту канала
    if not message.reply_to_message:
        return

    post_msg = message.reply_to_message
    post_id = post_msg.message_id

    user = message.from_user
    name = user.full_name or user.username or "Anonymous"

    # Определяем тип медиа
    media_type = None
    if message.sticker:
        media_type = "Sticker"
    elif message.photo:
        media_type = "Photo"

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

    # Создаём стикер
    sticker_img = create_sticker_image(name, text, avatar_url, media_type)

    # Удаляем оригинальный комментарий
    try:
        await message.delete()
    except Exception as e:
        logger.error("Delete error: " + str(e))

    # Отправляем как стикер (send_sticker требует .webp файл)
    try:
        await context.bot.send_sticker(
            chat_id=message.chat_id,
            sticker=sticker_img,
            reply_to_message_id=post_id
        )
        logger.info("Sent anonymous sticker for post: " + str(post_id))
    except Exception as e:
        logger.error("Sticker send error: " + str(e))
        # Fallback — отправляем как фото
        sticker_img.seek(0)
        await context.bot.send_photo(
            chat_id=message.chat_id,
            photo=sticker_img,
            reply_to_message_id=post_id
        )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error: " + str(context.error))


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Все типы сообщений в группах (чатах комментариев)
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.Sticker.ALL) & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_comment
    ))

    application.add_error_handler(error_handler)

    logger.info("Anonymous comment bot v4 started!")
    application.run_polling()


if __name__ == "__main__":
    main()
