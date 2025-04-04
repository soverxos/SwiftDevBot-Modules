"""
Модуль GeminiAI для SwiftDevBot
Интеграция с Google Gemini AI для обработки вопросов пользователей в Telegram.
"""

from aiogram import Router, types
from aiogram.filters import Command
import aiohttp
import logging
import os
from datetime import datetime
import asyncio
from dotenv import load_dotenv
import re

router = Router()
logger = logging.getLogger("gemini_ai")
kernel_data = None
GEMINI_KEY = None
DB_PATH = None
CONTEXT_PATH = None

async def init_db(db):
    """Инициализация таблиц базы данных для модуля GeminiAI."""
    await db.execute('''CREATE TABLE IF NOT EXISTS gemini_cache 
                        (question TEXT PRIMARY KEY, answer TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    await db.execute('''CREATE TABLE IF NOT EXISTS gemini_conversations 
                        (chat_id INTEGER, question TEXT, answer TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    await db.execute('''CREATE TABLE IF NOT EXISTS gemini_settings 
                        (chat_id INTEGER PRIMARY KEY, mode TEXT DEFAULT 'friendly')''')
    await db.execute('''CREATE TABLE IF NOT EXISTS gemini_rate_limit 
                        (chat_id INTEGER PRIMARY KEY, last_request TIMESTAMP)''')
    await db.commit()
    logger.info("📊 Таблицы базы данных для GeminiAI созданы или обновлены")

def setup(data):
    """Настройка модуля при загрузке."""
    global kernel_data, DB_PATH, CONTEXT_PATH, GEMINI_KEY
    dp = data["dp"]
    kernel_data = data
    DB_PATH = os.path.join(kernel_data["base_dir"], "data", "cache.db")
    CONTEXT_PATH = os.path.join(kernel_data["base_dir"], "data", "swiftdevbot_context.txt")
    env_path = os.path.join(kernel_data["base_dir"], ".env")
    load_dotenv(env_path)
    GEMINI_KEY = os.getenv("GEMINI_KEY")
    if not GEMINI_KEY:
        logger.error("GEMINI_KEY не найден в .env!")
        raise ValueError("GEMINI_KEY must be set in .env")
    
    asyncio.create_task(init_db(kernel_data["db"]))
    dp.include_router(router)
    logger.info("🛠 Модуль GeminiAI настроен")

def get_commands():
    """Возвращает список команд модуля."""
    return [
        {"command": "mode", "description": "🤖 Сменить режим ИИ (formal, friendly, sarcastic)", "admin": False, "icon": "🤖", "category": "GeminiAI"},
        {"command": "clearcache", "description": "🧹 Очистить кэш (админ)", "admin": True, "icon": "🧹", "category": "GeminiAI"}
    ]

async def format_response(text):
    """Форматирует текст ответа в HTML для Telegram."""
    text = re.sub(r'🤖\s*(?:\*\*.*?\*\*:?|SwiftDevBot:)\s*\n*', '', text)
    text = re.sub(r'\*+\s*', '', text)
    lines = text.split('\n')
    formatted = ""
    for line in lines:
        line = line.strip()
        if line:
            if ':' in line and len(line.split(':')[0].strip()) < 50:
                title, content = line.split(':', 1)
                formatted += f"<b>• {title.strip()}:</b> {content.strip()}\n\n"
            else:
                formatted += f"{line}\n\n"
    return formatted.strip()

async def ask_gemini(question, chat_id):
    """Запрос к Gemini AI с учетом кэша и контекста."""
    db = kernel_data["db"]
    async with db.execute("SELECT answer FROM gemini_cache WHERE question = ?", (question,)) as cursor:
        cached = await cursor.fetchone()
    if cached:
        logger.info(f"🔍 Найден кэшированный ответ для: {question}")
        return cached[0]

    async with db.execute("SELECT mode FROM gemini_settings WHERE chat_id = ?", (chat_id,)) as cursor:
        mode_result = await cursor.fetchone()
    mode = mode_result[0] if mode_result else "friendly"

    async with db.execute("SELECT question, answer FROM gemini_conversations WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 5", (chat_id,)) as cursor:
        history = await cursor.fetchall()
    context = "\n".join([f"Пользователь: {q}\nSwiftDevBot: {a}" for q, a in reversed(history)]) if history else ""

    try:
        with open(CONTEXT_PATH, "r", encoding="utf-8") as f:
            project_context = f.read()
            logger.info(f"Контекст из {CONTEXT_PATH}: {project_context[:100]}...")
    except FileNotFoundError:
        project_context = "Я — SwiftDevBot, Telegram-бот, созданный для помощи в разработке и ответов на вопросы."
        logger.error(f"Файл контекста {CONTEXT_PATH} не найден, использую стандартный контекст")

    mode_prompts = {
        "formal": "Отвечай формально и профессионально.",
        "friendly": "Отвечай дружелюбно и неформально.",
        "sarcastic": "Отвечай с сарказмом и юмором."
    }
    prompt = f"{project_context}\n\nТы — SwiftDevBot, русский ИИ-ассистент в Telegram. {mode_prompts[mode]} Учитывай контекст:\n{context}\nВопрос пользователя: {question}"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9, "topK": 1, "topP": 1, "maxOutputTokens": 2048, "stopSequences": []},
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
                    if response.status == 200:
                        result = await response.json()
                        if "candidates" in result and result["candidates"]:
                            answer = result["candidates"][0]["content"]["parts"][0]["text"]
                            formatted_answer = await format_response(answer)
                            full_answer = f"<b>🤖 SwiftDevBot:</b>\n\n{formatted_answer}"
                            await db.execute("INSERT OR REPLACE INTO gemini_cache (question, answer) VALUES (?, ?)", (question, full_answer))
                            await db.execute("INSERT INTO gemini_conversations (chat_id, question, answer) VALUES (?, ?, ?)", (chat_id, question, full_answer))
                            await db.commit()
                            return full_answer
                        return "❌ SwiftDevBot не смог ответить на ваш вопрос."
                    elif response.status == 503:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        return "❌ Сервер ИИ перегружен. Попробуй позже!"
                    else:
                        error_text = await response.text()
                        logger.error(f"Ошибка от Gemini: {response.status} - {error_text}")
                        return "❌ Не удалось получить ответ от ИИ."
        except Exception as e:
            logger.error(f"Ошибка запроса к Gemini (попытка {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
                continue
            return "❌ Произошла ошибка при обращении к ИИ. Попробуй позже!"

@router.message(lambda message: not message.text.startswith('/') and len(message.text) >= 3 and message.chat.type == "private")
async def handle_message(message: types.Message):
    """Обработка текстовых сообщений в личных чатах."""
    db = kernel_data["db"]
    async with db.execute("SELECT last_request FROM gemini_rate_limit WHERE chat_id = ?", (message.chat.id,)) as cursor:
        last = await cursor.fetchone()
    if last and (datetime.now() - datetime.fromisoformat(last[0])).total_seconds() < 5:
        await message.answer("⏳ Слишком быстро! Подожди 5 секунд.")
        return
    question = message.text
    answer = await ask_gemini(question, message.chat.id)
    await message.answer(answer, parse_mode="HTML")
    await db.execute("INSERT OR REPLACE INTO gemini_rate_limit (chat_id, last_request) VALUES (?, ?)", 
                     (message.chat.id, datetime.now().isoformat()))
    await db.commit()
    logger.info(f"🤖 Обработано сообщение от {message.from_user.id}: {question}")

@router.message(Command("mode"))
async def mode_command(message: types.Message):
    """Смена режима общения ИИ."""
    if not message.text.split(maxsplit=1)[1:]:
        await message.answer("Укажи режим: <code>/mode formal</code>, <code>/mode friendly</code>, <code>/mode sarcastic</code>", parse_mode="HTML")
        return
    mode = message.text.split(maxsplit=1)[1].lower()
    if mode not in ["formal", "friendly", "sarcastic"]:
        await message.answer("Доступные режимы: <code>formal</code>, <code>friendly</code>, <code>sarcastic</code>", parse_mode="HTML")
        return
    db = kernel_data["db"]
    await db.execute("INSERT OR REPLACE INTO gemini_settings (chat_id, mode) VALUES (?, ?)", (message.chat.id, mode))
    await db.commit()
    await message.answer(f"Режим изменён на: <code>{mode}</code>", parse_mode="HTML")
    logger.info(f"Режим для {message.from_user.id} изменён на {mode}")

@router.message(Command("clearcache"))
async def clear_cache_command(message: types.Message):
    """Очистка кэша и истории (только для админов)."""
    if message.from_user.id not in kernel_data["admin_ids"]:
        await message.answer("🚫 У вас нет доступа к этой команде!")
        return
    db = kernel_data["db"]
    await db.execute("DELETE FROM gemini_cache")
    await db.execute("DELETE FROM gemini_conversations")
    await db.commit()
    deleted_cache = db.total_changes
    await message.answer(f"🧹 Удалено <code>{deleted_cache}</code> записей из кэша и истории.", parse_mode="HTML")
    logger.info(f"Кэш и история очищены администратором {message.from_user.id}, удалено {deleted_cache} записей")

def get_settings(kernel_data):
    """Настройки модуля для отображения в /sysconf."""
    text = (
        "🤖 Модуль GeminiAI\n"
        f"API-ключ: {'Установлен' if GEMINI_KEY else 'Не установлен'}\n"
        "Этот модуль использует Google Gemini AI для ответов на вопросы.\n"
        "Настройки доступны только через .env файл."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    return text, keyboard

async def on_startup(data):
    """Действия при запуске модуля."""
    logger.info("🚀 Модуль GeminiAI запущен.")

async def on_shutdown(data):
    """Действия при завершении работы модуля."""
    logger.info("📴 Модуль GeminiAI завершает работу.")