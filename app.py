import os
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
# =========================================================

model = genai.GenerativeModel(
    model_name="gemini-3.6-flash",
    system_instruction=SYSTEM_PROMPT
)

# История чатов по chat_id (для продакшена лучше вынести в БД, память сбрасывается при рестарте)
chats = {}


def send_telegram_message(chat_id, text):
    requests.post(
        f"{TELEGRAM_API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )


def get_chat_session(chat_id):
    if chat_id not in chats:
        chats[chat_id] = model.start_chat(history=[])
    return chats[chat_id]


@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "message": "Сервер работает"})


# Этот адрес нужно будет один раз указать Telegram как webhook
@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True)

    message = update.get("message")
    if not message:
        return jsonify({"ok": True})

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text == "/start":
        chats.pop(chat_id, None)  # сброс истории при рестарте диалога
        send_telegram_message(chat_id, GREETING_MESSAGE)
        return jsonify({"ok": True})

    if not text:
        send_telegram_message(chat_id, "Я пока понимаю только текстовые сообщения.")
        return jsonify({"ok": True})

    try:
        session = get_chat_session(chat_id)
        response = session.send_message(text)
        send_telegram_message(chat_id, response.text)
    except Exception as e:
        send_telegram_message(chat_id, f"Произошла ошибка: {e}")

    return jsonify({"ok": True})


# Вызови один раз вручную (открыть в браузере), чтобы подключить webhook к Render-адресу
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
