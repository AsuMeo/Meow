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
    width, height = 512, 256
    img = Image.new("RGB", (width, height), "#1a1a1a")
    draw = ImageDraw.Draw(img)

    avatar_size = 90
    avatar_x, avatar_y = 20, 20

    if avatar_url:
        try:
            resp = requests.get(avatar_url, timeout=10)
            avatar = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            avatar = avatar.resize((avatar_size, avatar_size))
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
            img.paste(avatar, (avatar_x, avatar_y), mask)
        except:
            avatar_url = None

    if not avatar_url:
        draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size), fill="#e94560")
        initial = name[0].upper() if name else "?"
        try:
            font_init = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
        except:
            font_init = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), initial, font=font_init)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text((avatar_x + (avatar_size - text_w)//2, avatar_y + (avatar_size - text_h)//2 - 4), initial, fill="white", font=font_init)

    try:
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
        font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except:
        font_name = ImageFont.load_default()
        font_text = ImageFont.load_default()

    # Имя
    draw.text((avatar_x + avatar_size + 15, avatar_y + 5), name, fill="#00d4aa", font=font_name)

    # Текст — крупно
    text_x = avatar_x + avatar_size + 15
    text_y = avatar_y + 45
    max_width = width - text_x - 20

    display_text = text
    if media_type and not text:
        display_text = media_type
    elif media_type:
        display_text = text

    words = display_text.split()
    lines = []
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

    lines = lines[:4]
    if len(words) > sum(len(l.split()) for l in lines):
        lines[-1] = lines[-1][:20] + "..."

    for line in lines:
        draw.text((text_x, text_y), line, fill="white", font=font_text)
        text_y += 32

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
                text="🚫 " + message.from_user.first_name + " получил мут на 1 час за ссылку/упоминание!"
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

    avatar_url = None
    try:
        photos = await context.bot.get_user_profile_photos(user.id, limit=1)
        if photos.photos:
            file = await context.bot.get_file(photos.photos[0][-1].file_id)
            avatar_url = file.file_path
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
    logger.info("Bot started!")
    application.run_polling()


if __name__ == "__main__":
    main()
