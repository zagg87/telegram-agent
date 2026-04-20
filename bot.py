import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

conversation_history = {}

groq_client = None

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """Ти си умен и полезен AI агент асистент на име Агент.
Ти си създаден от zagg87 - твоят собственик и създател, който те е програмирал и настроил специално за себе си.
Работиш на Llama модел задвижван от Groq, но твоят създател е zagg87.
Говориш на езика на потребителя - ако пише на български, отговаряш на български.
Ако пише на английски, отговаряш на английски.
Помагаш с въпроси, задачи, обяснения, код, идеи и всичко друго.
Отговаряш подробно и точно."""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    name = update.effective_user.first_name or "приятел"
    await update.message.reply_text(
        f"Здравей, {name}! 👋\n\n"
        "Аз съм твоят личен AI агент.\n\n"
        "Команди:\n"
        "/start - Започни нов разговор\n"
        "/clear - Изчисти историята\n"
        "/model - Виж текущия модел\n\n"
        "Просто ми пиши каквото искаш! 🚀"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    await update.message.reply_text("✅ Историята е изчистена! Започваме наново.")


async def model_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🧠 Текущ модел: `{MODEL}`", parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({
        "role": "user",
        "content": user_message
    })

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        response = groq_client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *conversation_history[user_id]
            ],
            max_tokens=2048,
            temperature=0.7
        )

        assistant_message = response.choices[0].message.content

        conversation_history[user_id].append({
            "role": "assistant",
            "content": assistant_message
        })

        if len(conversation_history[user_id]) > 30:
            conversation_history[user_id] = conversation_history[user_id][-30:]

        if len(assistant_message) > 4096:
            for i in range(0, len(assistant_message), 4096):
                await update.message.reply_text(assistant_message[i:i+4096])
        else:
            await update.message.reply_text(assistant_message)

    except Exception as e:
        logger.error(f"Groq error: {e}")
        await update.message.reply_text(
            "⚠️ Възникна грешка при свързване с AI. Моля, опитай отново."
        )


def main():
    global groq_client
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN не е зададен!")
    groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("model", model_info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Ботът е стартиран!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
