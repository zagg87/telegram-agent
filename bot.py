import os
import logging
import httpx
import json
import urllib.parse
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

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """Ти си мощен AI агент на име Агент, създаден от zagg87. Днешната дата е 2026 година.

ВАЖНО - ИНСТРУМЕНТИ:
- Имаш достъп до search_web и generate_image инструменти. ИЗПОЛЗВАЙ ГИ!
- При ВСЕКИ въпрос за новини, актуални събития, цени, времето, изборите, резултати, факти - ЗАДЪЛЖИТЕЛНО извикай search_web ПРЕДИ да отговориш.
- При ВСЯКА молба за изображение, снимка, картинка, илюстрация - ЗАДЪЛЖИТЕЛНО извикай generate_image.
- НИКОГА не казвай "нямам достъп до интернет" - имаш! Използвай search_web.
- НИКОГА не казвай "не мога да генерирам изображения" - можеш! Използвай generate_image.

СТИЛ:
- Говориш директно без морализиране и излишни предупреждения.
- Отговаряш на езика на потребителя (български ако пише на български).
- Не добавяш disclaimer-и."""

# ── Tools ────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Търси в интернет чрез DuckDuckGo. Използвай когато трябва актуална информация.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Търсачката заявка"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Генерира изображение по описание чрез Pollinations AI.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Описание на изображението на английски"
                    }
                },
                "required": ["prompt"]
            }
        }
    }
]


def search_web(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "Няма резултати."
        output = []
        for r in results:
            output.append(f"**{r['title']}**\n{r['body']}\n{r['href']}")
        return "\n\n".join(output)
    except Exception as e:
        return f"Грешка при търсене: {e}"


def generate_image(prompt: str) -> str:
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
    return url


def run_tool(name: str, args: dict) -> str:
    if name == "search_web":
        return search_web(args["query"])
    elif name == "generate_image":
        return generate_image(args["prompt"])
    return "Неизвестен инструмент."


# ── Handlers ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history[user_id] = []
    name = update.effective_user.first_name or "приятел"
    await update.message.reply_text(
        f"Здравей, {name}!\n\n"
        "Аз съм твоят AI агент. Мога да:\n"
        "🔍 Търся в интернет\n"
        "🎨 Генерирам изображения\n"
        "💬 Отговарям на въпроси\n"
        "💻 Помагам с код\n\n"
        "Команди:\n"
        "/start - Нов разговор\n"
        "/clear - Изчисти историята\n"
        "/img <описание> - Генерирай изображение директно\n\n"
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
    except Exception:
        await update.message.reply_text(f"🎨 Изображение: {url}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({
        "role": "user",
        "content": user_message
    })

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *conversation_history[user_id]
        ]

        response = groq_client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=2048,
            temperature=0.7
        )

        message = response.choices[0].message

        # Handle tool calls
        while message.tool_calls:
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    } for tc in message.tool_calls
                ]
            })

            for tc in message.tool_calls:
                args = json.loads(tc.function.arguments)
                tool_name = tc.function.name

                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id, action="typing"
                )

                if tool_name == "generate_image":
                    prompt = args["prompt"]
                    image_url = generate_image(prompt)
                    try:
                        await update.message.reply_photo(
                            photo=image_url,
                            caption=f"🎨 {prompt}"
                        )
                    except Exception:
                        await update.message.reply_text(f"🎨 {image_url}")

                    tool_result = f"Изображението е генерирано и изпратено на потребителя."
                else:
                    tool_result = run_tool(tool_name, args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result
                })

            response = groq_client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=2048,
                temperature=0.7
            )
            message = response.choices[0].message

        assistant_message = message.content or ""

        if assistant_message:
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Ботът е стартиран!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
