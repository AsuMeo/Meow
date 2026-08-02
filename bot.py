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

ALLOWED_STICKER_SETS = {
    "KotikSAO", "SofiMy", "AsunaMe", "PinKa999", "KiraIArtyom6",
    "SARCAETSx", "Sarka01", "Podkaty01", "Kotayta993", "Xary01",
    "SamiMe01", "YumiMe01", "KiritoMe01", "StefanMe01", "KirAsu01",
    "MikuMe01", "Ylubawka", "KotTyanki", "MitaMe01", "YutaMe01",
    "Hikaru169", "LinehMe01", "AsunaCarnage", "KittyMe01", "AsunaSad01",
    "AsunaTyan", "Kirito55", "AsunaYuuki8", "SAOManga", "JonhDavy",
    "KiritoAsunaYukki", "MeowSao"
}

ALLOWED_EMOJI_SETS = {
    "SofiMe01", "KiraIArtem", "SARCAETS", "Sarka993", "NozhiMeow",
    "Kotyataaa993", "XaryEmoji", "Sami01Emoji", "MikuMeEmoji",
    "YlubawkaEmoji", "MitaMeEmoji", "AsuMeoArt", "YutaEmoji01",
    "HikaryEmoji01", "LineMeEmoji", "KittyMe01Emoji", "AsunaChanEmoji",
    "AsunaMeow"
}


def create_sticker_image(name, text, avatar_url=None, media_type=None, media_file=None):
    avatar_size = 140
    margin = 24
    text_x = avatar_size + margin * 2
    max_text_width = 512 - text_x - margin

    try:
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
        font_media = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except:
        font_name = ImageFont.load_default()
        font_text = ImageFont.load_default()
        font_media = ImageFont.load_default()

    temp_img = Image.new("RGB", (1, 1))
    temp_draw = ImageDraw.Draw(temp_img)

    display_text = text
    if media_type and not text:
        display_text = media_type

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

    lines = lines[:4]
    if len(words) > sum(len(l.split()) for l in lines):
        lines[-1] = lines[-1][:16] + "..."

    line_height = 44
    text_height = len(lines) * line_height
    name_height = 46

    # Если есть медиа-файл — добавляем его в стикер
    media_height = 0
    media_img = None
    if media_file:
        try:
            media_img = Image.open(io.BytesIO(media_file)).convert("RGBA")
            # Масштабируем медиа
            max_media_w = 512 - text_x - margin
            max_media_h = 200
            media_img.thumbnail((max_media_w, max_media_h), Image.LANCZOS)
            media_height = media_img.height + 10
        except:
            media_img = None

    content_height = max(avatar_size + margin * 2, name_height + text_height + media_height + margin * 3)
    height = min(content_height, 512)
    width = 512

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = 30
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
            logger.error("Avatar error: " + str(e))
            avatar_url = None

    if not avatar_url:
        draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size), fill="#2b5278")
        initial = name[0].upper() if name else "?"
        try:
            font_init = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        except:
            font_init = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), initial, font=font_init)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text((avatar_x + (avatar_size - text_w)//2, avatar_y + (avatar_size - text_h)//2 - 6), initial, fill="white", font=font_init)

    # Имя
    draw.text((text_x, margin + 8), name, fill="#53a9ff", font=font_name)

    # Текст
    text_y = margin + name_height + 14
    for line in lines:
        draw.text((text_x, text_y), line, fill="white", font=font_text)
        text_y += line_height

    # Медиа без обводки
    if media_img:
        media_x = text_x
        media_y = text_y + 5
        img.paste(media_img, (media_x, media_y), media_img)

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

    # Проверяем стикеры
    if message.sticker:
        sticker_set = message.sticker.set_name
        if sticker_set:
            # Проверяем разрешённые наборы
            is_allowed = False
            for allowed in ALLOWED_STICKER_SETS:
                if allowed.lower() in sticker_set.lower():
                    is_allowed = True
                    break
            for allowed in ALLOWED_EMOJI_SETS:
                if allowed.lower() in sticker_set.lower():
                    is_allowed = True
                    break

            if not is_allowed:
                try:
                    await message.delete()
                    await context.bot.send_message(
                        chat_id=message.chat_id,
                        text="🚫 " + name + ", этот стикер запрещён!"
                    )
                except:
                    pass
                return

    # Получаем медиа
    media_file = None
    media_type = None
    if message.photo:
        media_type = "Photo"
        try:
            photo = message.photo[-1]  # самое большое фото
            file = await context.bot.get_file(photo.file_id)
            media_file = file.download_as_bytearray()
        except Exception as e:
            logger.error("Photo download error: " + str(e))
    elif message.sticker:
        media_type = "Sticker"
        try:
            file = await context.bot.get_file(message.sticker.file_id)
            media_file = file.download_as_bytearray()
        except Exception as e:
            logger.error("Sticker download error: " + str(e))

    text = message.text or message.caption or ""

    avatar_url = None
    try:
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if photos.photos:
            file = await context.bot.get_file(photos.photos[0][-1].file_id)
            avatar_url = file.file_path
            logger.info("Avatar loaded for: " + name)
        else:
            logger.info("No avatar for: " + name)
    except Exception as e:
        logger.error("Avatar load error: " + str(e))

    sticker_img = create_sticker_image(name, text, avatar_url, media_type, media_file)

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
    logger.info("Bot v8 started!")
    application.run_polling()


if __name__ == "__main__":
    main()
