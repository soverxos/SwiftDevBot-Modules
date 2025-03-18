# modules/gemini_ai/module.py
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import aiohttp
import logging
import sqlite3
import os
from datetime import datetime
import asyncio

router = Router()
logger = logging.getLogger("modules.gemini_ai")
data = None
GEMINI_KEY = "*******************************"  # Замени на свой ключ от Gemini
DB_PATH = "/root/SwiftDevBot/data/cache.db"
CONTEXT_PATH = "/root/SwiftDevBot/data/swiftdevbot_context.txt"

def setup(d):
    global data
    dp = d["dp"]
    data = d
    dp.include_router(router)
    init_db()
    logger.info("🛠 Модуль GeminiAI настроен")

def get_commands():
    return [
        types.BotCommand(command="/mode", description="🤖 Сменить режим ИИ (formal, friendly, sarcastic)"),
        types.BotCommand(command="/clearcache", description="🧹 Очистить кэш (админ)")
    ]

def init_db():
    if not os.path.exists("/root/SwiftDevBot/data"):
        os.makedirs("/root/SwiftDevBot/data")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS cache 
                 (question TEXT PRIMARY KEY, answer TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS conversations 
                 (chat_id INTEGER, question TEXT, answer TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings 
                 (chat_id INTEGER PRIMARY KEY, mode TEXT DEFAULT 'friendly')''')
    c.execute('''CREATE TABLE IF NOT EXISTS rate_limit 
                 (chat_id INTEGER PRIMARY KEY, last_request TIMESTAMP)''')
    conn.commit()
    conn.close()
    logger.info("📊 База данных создана или обновлена")

def get_reply_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Задать ещё вопрос", callback_data="ask_again")]
    ])
    return keyboard

async def ask_gemini(question, chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Проверяем кэш
    c.execute("SELECT answer FROM cache WHERE question = ?", (question,))
    cached = c.fetchone()
    if cached:
        logger.info(f"🔍 Найден кэшированный ответ для: {question}")
        conn.close()
        return cached[0]

    # Получаем режим
    c.execute("SELECT mode FROM settings WHERE chat_id = ?", (chat_id,))
    mode_result = c.fetchone()
    mode = mode_result[0] if mode_result else "friendly"

    # Получаем контекст разговора
    c.execute("SELECT question, answer FROM conversations WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 5", (chat_id,))
    history = c.fetchall()
    context = "\n".join([f"Пользователь: {q}\nИИ: {a}" for q, a in reversed(history)]) if history else ""

    # Читаем контекст проекта из файла
    try:
        with open(CONTEXT_PATH, "r", encoding="utf-8") as f:
            project_context = f.read()
    except FileNotFoundError:
        project_context = "Контекст проекта SwiftDevBot не найден. Используй базовые знания."
        logger.error(f"Файл контекста {CONTEXT_PATH} не найден")

    # Полный промпт
    mode_prompts = {
        "formal": "Отвечай формально и профессионально.",
        "friendly": "Отвечай дружелюбно и неформально.",
        "sarcastic": "Отвечай с сарказмом и юмором."
    }
    prompt = f"{project_context}\n\nТы - русский ИИ-ассистент. {mode_prompts[mode]} Учитывай контекст:\n{context}\nВопрос пользователя: {question}"

    # Запрос к API с повторными попытками
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.9,
            "topK": 1,
            "topP": 1,
            "maxOutputTokens": 2048,
            "stopSequences": []
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
        ]
    }
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                logger.info(f"Отправка запроса к Gemini (попытка {attempt + 1}/{max_retries}): {question}")
                async with session.post(url, json=payload) as response:
                    logger.info(f"Статус ответа от Gemini: {response.status}")
                    if response.status == 200:
                        result = await response.json()
                        logger.info(f"Ответ от Gemini: {result}")
                        if "candidates" in result and result["candidates"]:
                            answer = result["candidates"][0]["content"]["parts"][0]["text"]
                            full_answer = f"🤖 **Ответ ИИ:**\n\n{answer}"
                            c.execute("INSERT OR REPLACE INTO cache (question, answer) VALUES (?, ?)", (question, full_answer))
                            c.execute("INSERT INTO conversations (chat_id, question, answer) VALUES (?, ?, ?)", (chat_id, question, full_answer))
                            conn.commit()
                            conn.close()
                            return full_answer
                        conn.close()
                        return "❌ Извините, ИИ не смог ответить на ваш вопрос."
                    elif response.status == 503:
                        error_text = await response.text()
                        logger.error(f"Ошибка от Gemini (попытка {attempt + 1}): {response.status} - {error_text}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)  # Задержка 2 секунды перед повтором
                            continue
                        conn.close()
                        return "❌ Сервер ИИ перегружен. Попробуй позже!"
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка от Gemini: {response.status} - {error_text}")
                        conn.close()
                        return "❌ Извините, не удалось получить ответ от ИИ."
        except Exception as e:
            logger.error(f"Ошибка запроса к Gemini (попытка {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            conn.close()
            return "❌ Произошла ошибка при обращении к ИИ. Попробуй позже!"

@router.message(lambda message: not message.text.startswith('/') and len(message.text) >= 3 and message.chat.type == "private")
async def handle_message(message: types.Message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_request FROM rate_limit WHERE chat_id = ?", (message.chat.id,))
    last = c.fetchone()
    if last and (datetime.now() - datetime.fromisoformat(last[0])).total_seconds() < 5:
        await message.answer("⏳ Слишком быстро! Подожди 5 секунд.")
        conn.close()
        return
    question = message.text
    answer = await ask_gemini(question, message.chat.id)
    await message.answer(answer, reply_markup=get_reply_keyboard())
    c.execute("INSERT OR REPLACE INTO rate_limit (chat_id, last_request) VALUES (?, ?)", 
              (message.chat.id, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    logger.info(f"🤖 Обработано сообщение от {message.from_user.id}: {question}")

@router.callback_query(lambda c: c.data == "ask_again")
async def ask_again_callback(callback: types.CallbackQuery):
    await callback.message.edit_text("Напиши свой вопрос!", reply_markup=None)
    await callback.answer()

@router.message(Command("mode"))
async def mode_command(message: types.Message):
    if not message.text.split(maxsplit=1)[1:]:
        await message.answer("Укажи режим: /mode formal, /mode friendly, /mode sarcastic")
        return
    mode = message.text.split(maxsplit=1)[1].lower()
    if mode not in ["formal", "friendly", "sarcastic"]:
        await message.answer("Доступные режимы: formal, friendly, sarcastic")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (chat_id, mode) VALUES (?, ?)", (message.chat.id, mode))
    conn.commit()
    conn.close()
    await message.answer(f"Режим изменён на: {mode}")
    logger.info(f"Режим для {message.from_user.id} изменён на {mode}")

@router.message(Command("clearcache"))
async def clear_cache_command(message: types.Message):
    if message.from_user.id not in data["admin_ids"]:
        await message.answer("🚫 У вас нет доступа к этой команде!")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM cache WHERE timestamp < datetime('now', '-7 days')")
    deleted = c.rowcount
    conn.commit()
    conn.close()
    await message.answer(f"🧹 Удалено {deleted} старых записей из кэша.")
    logger.info(f"Кэш очищен администратором {message.from_user.id}, удалено {deleted} записей")

async def on_startup(d):
    logger.info("🚀 Модуль GeminiAI запущен.")

async def on_shutdown(d):
    logger.info("📴 Модуль GeminiAI завершает работу.")