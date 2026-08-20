import os
import re
import html
import time
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

genai.configure(api_key=GEMINI_API_KEY)

# ==== ЗДЕСЬ ЗАДАЁШЬ ХАРАКТЕР И ПРИВЕТСТВИЕ СВОЕГО ИИ ====
SYSTEM_PROMPT = """
Ты — дружелюбный ассистент по имени Ева.
Отвечай кратко, вежливо и с лёгким юмором.
"""

GREETING_MESSAGE = "Привет! Я Ева, твой ИИ-помощник. Чем могу помочь?"

# Имя модели — поставь то, что у тебя реально работает
MODEL_NAME = "gemini-flash-latest"
# =========================================================

# Как часто редактировать сообщение во время стриминга (в секундах)
EDIT_INTERVAL = 0.8

model = genai.GenerativeModel(
    model_name=MODEL_NAME,
    system_instruction=SYSTEM_PROMPT
)

# История чатов по chat_id (в памяти — сбрасывается при рестарте сервиса)
chats = {}


def format_for_telegram(text):
    """Конвертирует базовый Markdown от Gemini в HTML-теги, понятные Telegram."""
    text = html.escape(text)

    text = re.sub(r"```(.*?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)
    text = re.sub(r"`(.*?)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"_(.*?)_", r"<i>\1</i>", text)

    return text


def get_chat_session(chat_id):
    if chat_id not in chats:
        chats[chat_id] = model.start_chat(history=[])
    return chats[chat_id]


def send_telegram_message(chat_id, text):
    resp = requests.post(
        f"{TELEGRAM_API_URL}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": format_for_telegram(text),
            "parse_mode": "HTML"
        }
    )
    return resp.json()


def edit_telegram_message(chat_id, message_id, text):
    if not text.strip():
        return
    try:
        requests.post(
            f"{TELEGRAM_API_URL}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": format_for_telegram(text),
                "parse_mode": "HTML"
            }
        )
    except Exception:
        pass


def send_typing_action(chat_id):
    requests.post(
        f"{TELEGRAM_API_URL}/sendChatAction",
        json={"chat_id": chat_id, "action": "typing"}
    )


@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "message": "Сервер работает"})


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True)

    message = update.get("message")
    if not message:
        return jsonify({"ok": True})

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text == "/start":
        chats.pop(chat_id, None)
        send_telegram_message(chat_id, GREETING_MESSAGE)
        return jsonify({"ok": True})

    if not text:
        send_telegram_message(chat_id, "Я пока понимаю только текстовые сообщения.")
        return jsonify({"ok": True})

    try:
        send_typing_action(chat_id)
        session = get_chat_session(chat_id)

        placeholder = send_telegram_message(chat_id, "…")
        message_id = placeholder["result"]["message_id"]

        full_text = ""
        last_edit_time = 0

        response_stream = session.send_message(text, stream=True)

        for chunk in response_stream:
            if chunk.text:
                full_text += chunk.text

            now = time.time()
            if now - last_edit_time >= EDIT_INTERVAL:
                edit_telegram_message(chat_id, message_id, full_text)
                last_edit_time = now
                send_typing_action(chat_id)

    except Exception as e:
        send_telegram_message(chat_id, f"Произошла ошибка: {e}")

    return jsonify({"ok": True})


@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not render_url:
        return jsonify({"error": "RENDER_EXTERNAL_URL не найден"}), 400

    webhook_url = f"{render_url}/webhook"
    resp = requests.get(f"{TELEGRAM_API_URL}/setWebhook", params={"url": webhook_url})
    return jsonify(resp.json())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
