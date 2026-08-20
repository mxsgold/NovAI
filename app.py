import os
import re
import html
import time
import threading
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

MODEL_NAME = "gemini-flash-latest"
# =========================================================

EDIT_INTERVAL = 0.8       # как часто обновлять текст во время генерации
DOTS_INTERVAL = 0.3       # как часто крутить анимацию точек (0.1 сек = риск лимитов Telegram, поставил 0.3 для надёжности)

model = genai.GenerativeModel(
    model_name=MODEL_NAME,
    system_instruction=SYSTEM_PROMPT
)

chats = {}


def format_for_telegram(text):
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


def animate_dots(chat_id, message_id, stop_event):
    """Крутит анимацию . -> .. -> ... -> . по кругу, пока не установлен stop_event."""
    dots_cycle = [".", "..", "..."]
    i = 0
    while not stop_event.is_set():
        edit_telegram_message(chat_id, message_id, dots_cycle[i % 3])
        i += 1
        stop_event.wait(DOTS_INTERVAL)


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

        placeholder = send_telegram_message(chat_id, ".")
        message_id = placeholder["result"]["message_id"]

        # Запускаем анимацию точек в фоне, пока ждём первый кусок текста
        stop_event = threading.Event()
        dots_thread = threading.Thread(
            target=animate_dots, args=(chat_id, message_id, stop_event)
        )
        dots_thread.start()

        full_text = ""
        last_edit_time = 0
        first_chunk_received = False

        response_stream = session.send_message(text, stream=True)

        for chunk in response_stream:
            if chunk.text:
                if not first_chunk_received:
                    # Пришёл первый реальный текст — останавливаем анимацию точек
                    stop_event.set()
                    dots_thread.join()
                    first_chunk_received = True
                    last_edit_time = 0  # чтобы сразу показать первый кусок текста

                full_text += chunk.text

            now = time.time()
            if first_chunk_received and now - last_edit_time >= EDIT_INTERVAL:
                edit_telegram_message(chat_id, message_id, full_text)
                last_edit_time = now
                send_typing_action(chat_id)

        # На случай если ответ пустой или анимация не была остановлена
        if not stop_event.is_set():
            stop_event.set()
            dots_thread.join()

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
