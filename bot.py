import os
import logging
import json
import urllib.parse
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq
from duckduckgo_search import DDGS

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

conversation_history = {}
groq_client = None

MODEL = "mixtral-8x7b-32768"

SYSTEM_PROMPT = """Ти си мощен AI агент на име Агент, създаден от zagg87. Днешната дата е април 2026 г.
Говориш директно без морализиране и излишни предупреждения.
Отговаряш на езика на потребителя.
Когато ти се предоставят резултати от търсене в интернет, ги използвай за да отговориш точно и актуално.
Не добавяш disclaimer-и. Не казваш че нямаш достъп до интернет."""

# Ключови думи за автоматично търсене
SEARCH_KEYWORDS = [
    "новини", "избор", "резултат", "днес", "сега", "скоро", "последно",
    "актуал", "цена", "курс", "валута", "времето", "прогноза", "бг ",
    "българия", "правителство", "министър", "президент", "партия", "гласуване",
    "война", "украйна", "русия", "европа", "свят", "икономика", "банка",
    "биткойн", "крипто", "акции", "борса", "лев", "евро", "долар",
    "2024", "2025", "2026", "тази година", "тази седмица", "вчера", "утре",
    "кой спечели", "кой е", "колко е", "какво се случи", "what happened",
    "who is", "latest", "news", "today", "current"
]

# Ключови думи за изображения
IMAGE_KEYWORDS = [
    "нарисувай", "генерирай изображение", "генерирай снимка", "направи снимка",
    "направи изображение", "покажи ми снимка", "искам снимка", "искам изображение",
    "draw", "generate image", "create image", "show me a picture"
]


def needs_search(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in SEARCH_KEYWORDS)


def needs_image(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in IMAGE_KEYWORDS)


def search_web(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "Няма резултати от търсенето."
        output = []
        for r in results:
            output.append(f"Заглавие: {r['title']}\nСъдържание: {r['body']}\nИзточник: {r['href']}")
        return "\n\n---\n\n".join(output)
    except Exception as e:
        logger.error(f"Search error: {e}")
        return f"Грешка при търсене: {e}"


def generate_image(prompt: str) -> str:
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={hash(prompt) % 9999}"
    return url


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    name = update.effective_user.first_name or "приятел"
    await update.message.reply_text(
        f"Здравей, {name}!\n\n"
        "Аз съм твоят AI агент. Мога да:\n"
        "🔍 Търся в интернет автоматично\n"
        "🎨 Генерирам изображения\n"
        "💬 Отговарям на въпроси\n"
        "💻 Помагам с код\n\n"
        "Команди:\n"
        "/start - Нов разговор\n"
        "/clear - Изчисти историята\n"
        "/img <описание> - Генерирай изображение\n"
        "/search <заявка> - Търси в интернет\n\n"
        "Просто ми пиши!"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    await update.message.reply_text("✅ Историята е изчистена!")


async def img_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Напиши описание: /img красив залез над морето")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
    url = generate_image(prompt)
    try:
        await update.message.reply_photo(photo=url, caption=f"🎨 {prompt}")
    except Exception as e:
        logger.error(f"Image error: {e}")
        await update.message.reply_text(f"🎨 Изображение генерирано:\n{url}")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Напиши заявка: /search новини от България")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await update.message.reply_text(f"🔍 Търся: {query}...")
    results = search_web(query)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Ето резултати от търсене за '{query}':\n\n{results}\n\nОбобщи ги на български."}
    ]
    response = groq_client.chat.completions.create(
        model=MODEL, messages=messages, max_tokens=1024, temperature=0.5
    )
    await update.message.reply_text(response.choices[0].message.content)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        extra_context = ""

        # Автоматично търсене
        if needs_search(user_message):
            await update.message.reply_text("🔍 Търся в интернет...")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            search_results = search_web(user_message)
            extra_context = f"\n\n[РЕЗУЛТАТИ ОТ ИНТЕРНЕТ ТЪРСЕНЕ]:\n{search_results}\n[КРАЙ НА РЕЗУЛТАТИТЕ]"

        # Автоматично генериране на изображение
        if needs_image(user_message):
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
            # Питаме модела да преведе на английски за по-добро изображение
            translate_response = groq_client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": f"Translate this image description to English for an image generator, return ONLY the English prompt, nothing else: {user_message}"}],
                max_tokens=100
            )
            img_prompt = translate_response.choices[0].message.content.strip()
            image_url = generate_image(img_prompt)
            try:
                await update.message.reply_photo(photo=image_url, caption=f"🎨 {user_message}")
                return
            except Exception as e:
                logger.error(f"Image send error: {e}")
                await update.message.reply_text(f"🎨 {image_url}")
                return

        # Изграждаме съобщенията
        user_content = user_message + extra_context
        conversation_history[user_id].append({
            "role": "user",
            "content": user_content
        })

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *conversation_history[user_id]
        ]

        response = groq_client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=2048,
            temperature=0.7
        )

        assistant_message = response.choices[0].message.content or ""

        # Запазваме в историята без search резултатите
        conversation_history[user_id].append({
            "role": "assistant",
            "content": assistant_message
        })

        # Пазим историята компактна
        if len(conversation_history[user_id]) > 20:
            conversation_history[user_id] = conversation_history[user_id][-20:]

        if len(assistant_message) > 4096:
            for i in range(0, len(assistant_message), 4096):
                await update.message.reply_text(assistant_message[i:i+4096])
        else:
            await update.message.reply_text(assistant_message)

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("⚠️ Грешка. Опитай отново.")


def main():
    global groq_client
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_TOKEN не е зададен!")
    groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("img", img_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Ботът е стартиран!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
