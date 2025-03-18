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
logger = logging.getLogger("modules.gemini_ai")
data = None
GEMINI_KEY = None
DB_PATH = None
CONTEXT_PATH = None

async def init_db(db):
    await db.execute('''CREATE TABLE IF NOT EXISTS cache 
                        (question TEXT PRIMARY KEY, answer TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    await db.execute('''CREATE TABLE IF NOT EXISTS conversations 
                        (chat_id INTEGER, question TEXT, answer TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    await db.execute('''CREATE TABLE IF NOT EXISTS settings 
                        (chat_id INTEGER PRIMARY KEY, mode TEXT DEFAULT 'friendly')''')
    await db.execute('''CREATE TABLE IF NOT EXISTS rate_limit 
                        (chat_id INTEGER PRIMARY KEY, last_request TIMESTAMP)''')
    await db.commit()
    logger.info("📊 Таблицы базы данных для GeminiAI созданы или обновлены")

async def setup(d):
    global data, DB_PATH, CONTEXT_PATH, GEMINI_KEY
    dp = d["dp"]
    data = d
    DB_PATH = os.path.join(data["base_dir"], "data", "cache.db")
    CONTEXT_PATH = os.path.join(data["base_dir"], "data", "swiftdevbot_context.txt")
    env_path = os.path.join(data["base_dir"], ".env")
    load_dotenv(env_path)
    GEMINI_KEY = os.getenv("GEMINI_KEY")
    if not GEMINI_KEY:
        logger.error("GEMINI_KEY не найден в .env!")
        raise ValueError("GEMINI_KEY must be set in .env")
    
    await init_db(data["db"])
    
    dp.include_router(router)
    logger.info("🛠 Модуль GeminiAI настроен")

def get_commands():
    return [
        types.BotCommand(command="/mode", description="🤖 Сменить режим ИИ (formal, friendly, sarcastic)"),
        types.BotCommand(command="/clearcache", description="🧹 Очистить кэш (админ)")
    ]

async def format_response(text):
    """Форматирует текст ответа в HTML для красивого отображения в Telegram."""
    # Удаляем любые заголовки от Gemini и Markdown-форматирование
    text = re.sub(r'🤖\s*(?:\*\*.*?\*\*:?|SwiftDevBot:)\s*\n*', '', text)  # Удаляем любые варианты заголовков
    text = re.sub(r'\*+\s*', '', text)  # Удаляем Markdown-звёздочки
    # Разбиваем текст на строки
    lines = text.split('\n')
    formatted = ""
    for line in lines:
        line = line.strip()
        if line:
            # Обрабатываем строки с двоеточием как заголовки списка
            if ':' in line and len(line.split(':')[0].strip()) < 50:
                title, content = line.split(':', 1)
                formatted += f"<b>• {title.strip()}:</b> {content.strip()}\n\n"
            else:
                formatted += f"{line}\n\n"
    return formatted.strip()

async def ask_gemini(question, chat_id):
    db = data["db"]
    cursor = await db.execute("SELECT answer FROM cache WHERE question = ?", (question,))
    cached = await cursor.fetchone()
    if cached:
        logger.info(f"🔍 Найден кэшированный ответ для: {question}")
        return cached[0]

    cursor = await db.execute("SELECT mode FROM settings WHERE chat_id = ?", (chat_id,))
    mode_result = await cursor.fetchone()
    mode = mode_result[0] if mode_result else "friendly"

    cursor = await db.execute("SELECT question, answer FROM conversations WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 5", (chat_id,))
    history = await cursor.fetchall()
    context = "\n".join([f"Пользователь: {q}\nSwiftDevBot: {a}" for q, a in reversed(history)]) if history else ""

    try:
        with open(CONTEXT_PATH, "r", encoding="utf-8") as f:
            project_context = f.read()
            logger.info(f"Контекст из {CONTEXT_PATH}: {project_context[:100]}...")  # Логируем начало контекста
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
                            formatted_answer = await format_response(answer)
                            full_answer = f"<b>🤖 SwiftDevBot:</b>\n\n{formatted_answer}"
                            await db.execute("INSERT OR REPLACE INTO cache (question, answer) VALUES (?, ?)", (question, full_answer))
                            await db.execute("INSERT INTO conversations (chat_id, question, answer) VALUES (?, ?, ?)", (chat_id, question, full_answer))
                            await db.commit()
                            return full_answer
                        return "❌ SwiftDevBot не смог ответить на ваш вопрос."
                    elif response.status == 503:
                        error_text = await response.text()
                        logger.error(f"Ошибка от Gemini (попытка {attempt + 1}): {response.status} - {error_text}")
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
    db = data["db"]
    cursor = await db.execute("SELECT last_request FROM rate_limit WHERE chat_id = ?", (message.chat.id,))
    last = await cursor.fetchone()
    if last and (datetime.now() - datetime.fromisoformat(last[0])).total_seconds() < 5:
        await message.answer("⏳ Слишком быстро! Подожди 5 секунд.")
        return
    question = message.text
    answer = await ask_gemini(question, message.chat.id)
    await message.answer(answer, parse_mode="HTML")
    await db.execute("INSERT OR REPLACE INTO rate_limit (chat_id, last_request) VALUES (?, ?)", 
                     (message.chat.id, datetime.now().isoformat()))
    await db.commit()
    logger.info(f"🤖 Обработано сообщение от {message.from_user.id}: {question}")

@router.message(Command("mode"))
async def mode_command(message: types.Message):
    if not message.text.split(maxsplit=1)[1:]:
        await message.answer("Укажи режим: <code>/mode formal</code>, <code>/mode friendly</code>, <code>/mode sarcastic</code>", parse_mode="HTML")
        return
    mode = message.text.split(maxsplit=1)[1].lower()
    if mode not in ["formal", "friendly", "sarcastic"]:
        await message.answer("Доступные режимы: <code>formal</code>, <code>friendly</code>, <code>sarcastic</code>", parse_mode="HTML")
        return
    db = data["db"]
    await db.execute("INSERT OR REPLACE INTO settings (chat_id, mode) VALUES (?, ?)", (message.chat.id, mode))
    await db.commit()
    await message.answer(f"Режим изменён на: <code>{mode}</code>", parse_mode="HTML")
    logger.info(f"Режим для {message.from_user.id} изменён на {mode}")

@router.message(Command("clearcache"))
async def clear_cache_command(message: types.Message):
    if message.from_user.id not in data["admin_ids"]:
        await message.answer("🚫 У вас нет доступа к этой команде!")
        return
    db = data["db"]
    await db.execute("DELETE FROM cache")
    await db.execute("DELETE FROM conversations")
    await db.commit()
    deleted_cache = db.total_changes
    await message.answer(f"🧹 Удалено <code>{deleted_cache}</code> записей из кэша и истории.", parse_mode="HTML")
    logger.info(f"Кэш и история очищены администратором {message.from_user.id}, удалено {deleted_cache} записей")

async def on_startup(d):
    logger.info("🚀 Модуль GeminiAI запущен.")

async def on_shutdown(d):
    logger.info("📴 Модуль GeminiAI завершает работу.")
