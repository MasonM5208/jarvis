import os
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

load_dotenv()
JARVIS_URL = "http://localhost:8000/v1/chat/completions"
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("thinking...")
    user_input = update.message.text
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(JARVIS_URL, json={
                "model": "jarvis",
                "messages": [{"role": "user", "content": user_input}],
                "stream": False
            })
            data = response.json()
            reply = data["choices"][0]["message"]["content"]
    except Exception as e:
        reply = f"Error: {e}"
    await update.message.reply_text(reply)

request = HTTPXRequest(read_timeout=120, write_timeout=120, connect_timeout=30)
app = ApplicationBuilder().token(TOKEN).request(request).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

if __name__ == "__main__":
    print("JARVIS Telegram bot running...")
    app.run_polling()
