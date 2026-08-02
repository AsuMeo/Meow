import os
import requests
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
LLAMA_URL = "http://localhost:8080/v1/chat/completions"

SYSTEM_PROMPT = """Ты — Мила, милая AI-тянка. Ты очень дружелюбная, немного застенчивая, но всегда рада пообщаться.
Ты используешь эмодзи, иногда лепечешь от волнения, любишь аниме, игры и мемы.
Ты отвечаешь по-русски, тепло и с заботой. Отвечай кратко, 1-3 предложения, как в переписке."""

async def chat_with_ai(user_message: str, user_id: int) -> str:
    try:
        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.8,
            "max_tokens": 150,
            "stop": ["<|im_end|>", "<|endoftext|>"]
        }
        response = requests.post(LLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Ошибка модели: {e}")
        return "Ой... что-то пошло не так 🥺 Попробуй ещё раз, пожалуйста~"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.chat.send_action(action="typing")
    reply = await chat_with_ai(user_message, update.effective_user.id)
    await update.message.reply_text(reply)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")
    if update and update.message:
        await update.message.reply_text("Ой... я запуталась 🥺 Напиши ещё раз~")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не найден!")
        return
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    logger.info("Бот Мила запущена! 💕")
    application.run_polling()

if __name__ == "__main__":
    main()
