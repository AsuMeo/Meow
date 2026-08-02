import os
import io
import re
import logging
import requests
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
LINK_PATTERN = re.compile(r'https?://|www\.|t\.me/|@[\w_]+')

def create_sticker_image(name, text, avatar_url=None, media_type=None):
    # Динамическая высота под текст
    avatar_size = 110
    margin = 20
    text_x = avatar_size + margin * 2
    max_text_width = 512 - text_x - margin

    try:
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
    except:
        font_name = ImageFont.load_default()
        font_text = ImageFont.load_default()

    # Считаем высоту текста
    display_text = text
    if media_type and not text:
        display_text = media_type

    temp_img = Image.new("RGB", (1, 1))
    temp_draw = ImageDraw.Draw(temp_img)

    words = display_text.split()
    lines = []
    current_line = ""
    for word in words:
        test = current_line + " " + word if current_line else word
        bbox = temp_draw.textbbox((0, 0), test, font=font_text)
        if bbox[2] - bbox[0] <= max_text_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    lines = lines[:5]
    if len(words) > sum(len(l.split()) for l in lines):
        lines[-1] = lines[-1][:22] + "..."

    line_height = 34
    text_height = len(lines) * line_height
    name_height = 36

    # Минимальная высота — под аватарку, максимум — 512
    content_height = max(avatar_size + margin * 2, name_height + text_height + margin * 3)
    height = min(content_height, 512)
    width = 512

    # Создаём с закруглёнными краями через маску
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Фон стикера — закруглённый прямоугольник
    radius = 25
    draw.rounded_rectangle((0, 0, width, height), radius=radius, fill="#1a1a1a")

    # Аватарка
    avatar_y = margin
    avatar_x = margin

    if avatar_url:
        try:
            resp = requests.get(avatar_url, timeout=10)
            avatar = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            avatar = avatar.resize((avatar_size, avatar_size))
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
            img.paste(avatar, (avatar_x, avatar_y), mask)
        except Exception as e:
            logger.error("Avatar load error: " + str(e))
            avatar_url = None

    if not avatar_url:
        # Круг с инициалом
        draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size), fill="#e94560")
        initial = name[0].upper() if name else "?"
        try:
            font_init = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
        except:
            font_init = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), initial, font=font_init)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text((avatar_x + (avatar_size - text_w)//2, avatar_y + (avatar_size - text_h)//2 - 5), initial, fill="white", font=font_init)

    # Имя — крупное, зелёное
    draw.text((text_x, margin + 5), name, fill="#00d4aa", font=font_name)

    # Текст — белый, крупный
    text_y = margin + name_height + 10
    for line in lines:
        draw.text((text_x, text_y), line, fill="white", font=font_text)
        text_y += line_height

    # Конвертируем в WEBP
    webp_buffer = io.BytesIO()
    img.save(webp_buffer, format="WEBP")
    webp_buffer.seek(0)
    return webp_buffer


async def check_spam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.message
    if not message:
        return False
    text = message.text or message.caption or ""
    if LINK_PATTERN.search(text):
        try:
            await message.delete()
            until_date = int(message.date.timestamp()) + 3600
            await context.bot.restrict_chat_member(
                chat_id=message.chat_id,
                user_id=message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            await context.bot.send_message(
                chat_id=message.chat_id,
                text="🚫 " + message.from_user.first_name + " получил мут на 1 час!"
            )
        except Exception as e:
            logger.error("Mute error: " + str(e))
        return True
    return False


async def handle_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    if message.from_user and message.from_user.is_bot:
        return
    if await check_spam(update, context):
        return
    if not message.reply_to_message:
        return

    post_id = message.reply_to_message.message_id
    user = message.from_user
    name = user.full_name or user.username or "Anonymous"

    media_type = None
    if message.sticker:
        media_type = "Sticker"
    elif message.photo:
        media_type = "Photo"

    text = message.text or message.caption or ""

    # Получаем аватарку — пробуем разные способы
    avatar_url = None
    try:
        # Способ 1: через get_user_profile_photos
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if photos.photos:
            file = await context.bot.get_file(photos.photos[0][-1].file_id)
            avatar_url = file.file_path
            logger.info("Avatar loaded via get_user_profile_photos")
    except Exception as e:
        logger.error("Avatar error 1: " + str(e))

    # Способ 2: через username (если публичный профиль)
    if not avatar_url and user.username:
        try:
            # Telegram не даёт прямой URL, но можно через t.me
            # Это не всегда работает, но попробуем
            resp = requests.get("https://t.me/" + user.username, timeout=5)
            # Парсим аватарку из HTML — сложно, пропускаем
            pass
        except:
            pass

    sticker_img = create_sticker_image(name, text, avatar_url, media_type)

    try:
        await message.delete()
    except Exception as e:
        logger.error("Delete error: " + str(e))

    try:
        await context.bot.send_sticker(
            chat_id=message.chat_id,
            sticker=sticker_img,
            reply_to_message_id=post_id
        )
        logger.info("Sticker sent for post: " + str(post_id))
    except Exception as e:
        logger.error("Sticker error: " + str(e))
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
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.Sticker.ALL) & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_comment
    ))
    application.add_error_handler(error_handler)
    logger.info("Bot v6 started!")
    application.run_polling()


if __name__ == "__main__":
    main()
