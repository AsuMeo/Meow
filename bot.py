import os
import asyncio
import logging
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")  # ID канала, например -1001234567890

TEXT = "Подпишись, мяу ~"


async def animate_post(bot: Bot, chat_id: int, message_id: int):
    """Анимация печати — редактирует пост по одной букве"""
    current_text = ""
    index = 0

    while True:
        if index <= len(TEXT):
            current_text = TEXT[:index]
            index += 1
        else:
            # Начинаем сначала
            index = 0
            current_text = ""
            await asyncio.sleep(1)
            continue

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=current_text
            )
            await asyncio.sleep(1)
        except Exception as e:
            error_str = str(e)
            # Если слишком часто редактируем — ждём
            if "Too Many Requests" in error_str or "retry after" in error_str:
                # Парсим время ожидания
                import re
                match = re.search(r'retry after (\d+)', error_str)
                if match:
                    wait_time = int(match.group(1))
                    logger.info("Rate limit, waiting " + str(wait_time) + " seconds")
                    await asyncio.sleep(wait_time + 1)
                else:
                    logger.info("Rate limit, waiting 5 seconds")
                    await asyncio.sleep(5)
            elif "message is not modified" in error_str:
                # Игнорируем, если текст не изменился
                await asyncio.sleep(1)
            else:
                logger.error("Edit error: " + error_str)
                await asyncio.sleep(3)


async def start_animation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает анимацию в канале"""
    if not CHANNEL_ID:
        await update.message.reply_text("CHANNEL_ID не настроен!")
        return

    chat_id = int(CHANNEL_ID)

    # Создаём начальный пост
    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=".")
        logger.info("Post created: " + str(msg.message_id))
    except Exception as e:
        await update.message.reply_text("Ошибка создания поста: " + str(e))
        return

    # Запускаем анимацию в фоне
    asyncio.create_task(animate_post(context.bot, chat_id, msg.message_id))

    await update.message.reply_text("Анимация запущена в канале!")


async def stop_animation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Останавливает анимацию (не реализовано полностью — нужно хранить task)"""
    await update.message.reply_text("Чтобы остановить — перезапусти бота или удали пост вручную.")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error: " + str(context.error))


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found!")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start_anim", start_animation))
    application.add_handler(CommandHandler("stop", stop_animation))
    application.add_error_handler(error_handler)

    logger.info("Typing post bot started!")
    application.run_polling()


if __name__ == "__main__":
    main()
