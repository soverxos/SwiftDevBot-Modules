# /modules/gemini_ai/module.py

import logging
from logging.handlers import RotatingFileHandler
import os
import asyncio
import aiosqlite
import re
import json # Добавили для работы с config.json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple, Optional

import aiohttp

from aiogram import Router, types, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.filters.command import CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup,
    InlineKeyboardMarkup, InlineKeyboardButton # Добавили для настроек
)
from aiogram.exceptions import TelegramBadRequest

# Импорт cryptography для шифрования
try:
    from cryptography.fernet import Fernet, InvalidToken
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None # Определяем как None, если библиотека не найдена
    InvalidToken = None
    logging.getLogger(__name__).error("Библиотека 'cryptography' не найдена! Шифрование ключей API невозможно. Установите: pip install cryptography")


# Попробуем импортировать black
try:
    import black
    BLACK_AVAILABLE = True
except ImportError:
    BLACK_AVAILABLE = False
    black = None

# --- Логгер модуля ---
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# --- Роутер модуля ---
router = Router()

# --- Состояния FSM ---
class GeminiAIStates(StatesGroup):
    waiting_for_api_key = State()
    # Добавьте другие состояния, если нужно

# --- Кнопка Отмены для FSM ---
cancel_button = KeyboardButton(text="/cancel")
cancel_kb = ReplyKeyboardMarkup(keyboard=[[cancel_button]], resize_keyboard=True, one_time_keyboard=True)

# --- Переменные уровня модуля ---
CONTEXT_PATH: str | None = None
DEFAULT_CONTEXT: str = "Я — SwiftDevBot, Telegram-бот, созданный для помощи в разработке и ответов на вопросы."

# --- Инициализация БД ---
async def init_db(kernel_data: Dict[str, Any]):
    """Инициализация таблиц модуля в основной БД."""
    db = kernel_data.get("db")
    if db is None: logger.error("❌ БД недоступна для инициализации GeminiAI"); return
    try:
        await db.execute('''CREATE TABLE IF NOT EXISTS gemini_cache (question TEXT PRIMARY KEY, answer TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS gemini_conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, question TEXT, answer TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS gemini_settings (chat_id INTEGER PRIMARY KEY, mode TEXT DEFAULT 'friendly')''')
        await db.execute('''CREATE TABLE IF NOT EXISTS gemini_rate_limit (chat_id INTEGER PRIMARY KEY, last_request TIMESTAMP)''')
        await db.execute("CREATE INDEX IF NOT EXISTS idx_gemini_conv_chat_id ON gemini_conversations (chat_id)")
        await db.commit()
        logger.info("📊 Таблицы GeminiAI инициализированы.")
    except aiosqlite.Error as e: logger.error(f"❌ Ошибка init_db GeminiAI: {e}", exc_info=True)

# --- Вспомогательные функции ---
async def load_project_context() -> str:
    """Асинхронно загружает контекст проекта из файла."""
    # ... (оставляем как было или меняем на aiofiles) ...
    if CONTEXT_PATH and os.path.exists(CONTEXT_PATH):
        try:
            with open(CONTEXT_PATH, "r", encoding="utf-8") as f:
                content = f.read()
                logger.info(f"Контекст загружен из {CONTEXT_PATH}: {len(content)} симв.")
                return content
        except OSError as e: logger.error(f"Ошибка чтения {CONTEXT_PATH}: {e}"); return DEFAULT_CONTEXT
    else: logger.warning(f"Файл {CONTEXT_PATH} не найден."); return DEFAULT_CONTEXT

def format_response(text: str) -> str:
    """Упрощенное форматирование ответа Gemini."""
    text = re.sub(r'^🤖\s*(\*\*.*?\*\*[:\s]*)?(SwiftDevBot[:\s]*)?', '', text).strip()
    text = text.replace('*', '')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    formatted_lines = []
    for line in lines:
         if len(line) < 60 or ':' in line.split(' ', 1)[0]: # Чуть изменим логику заголовка
              formatted_lines.append(f"<b>{line}</b>")
         else: formatted_lines.append(line)
    return "\n\n".join(formatted_lines)

async def _reply_with_fallback(message: types.Message, text: str, **kwargs):
     """Отправляет ответ, пытаясь с HTML, при ошибке - без."""
     try: await message.reply(text, parse_mode="HTML", **kwargs)
     except TelegramBadRequest as e:
         if "can't parse entities" in str(e):
             logger.warning(f"Ошибка HTML: {e}. Попытка без форматирования."); safe_text = re.sub(r"<[^>]*>", "", text)
             await message.reply(safe_text, parse_mode=None, **kwargs)
         else: logger.error(f"Ошибка TG BadRequest: {e}"); await message.reply(f"❌ Ошибка: {e.message}", **kwargs)
     except Exception as e: logger.error(f"Ошибка отправки: {e}", exc_info=True); await message.reply("❌ Ошибка отправки.", **kwargs)

def _get_decrypted_key(kernel_data: Dict[str, Any]) -> str | None:
    """Получает и дешифрует ключ API из конфига."""
    fernet = kernel_data.get("encryption_key")
    encrypted_key = kernel_data.get("config", {}).get("module_secrets", {}).get("gemini_ai")

    if not fernet: logger.error("Ключ шифрования (Fernet) недоступен!"); return None
    if not encrypted_key: logger.debug("Зашифрованный ключ GeminiAI не найден в конфиге."); return None

    try:
        decrypted_key = fernet.decrypt(encrypted_key.encode()).decode()
        return decrypted_key
    except InvalidToken: logger.error("Неверный токен! Не удалось дешифровать ключ GeminiAI."); return None
    except Exception as e: logger.error(f"Ошибка дешифровки ключа GeminiAI: {e}", exc_info=True); return None

# --- Основная функция запроса к Gemini ---
async def ask_gemini(kernel_data: Dict[str, Any], question: str, chat_id: int) -> str:
    """Запрос к Gemini AI."""
    db = kernel_data.get("db")
    gemini_key = _get_decrypted_key(kernel_data) # Получаем дешифрованный ключ

    if db is None: logger.error("❌ БД недоступна"); return "❌ Ошибка: БД недоступна."
    if not gemini_key: return "❌ Ошибка: API ключ Gemini не настроен или не может быть дешифрован. Установите через /sysconf."

    # 1. Проверка кэша
    # ... (без изменений) ...
    try:
        async with db.execute("SELECT answer FROM gemini_cache WHERE question = ?", (question,)) as cursor:
            cached = await cursor.fetchone()
        if cached: logger.info(f"🔍 Кэш: '{question[:50]}...'"); return cached[0]
    except aiosqlite.Error as e: logger.error(f"Ошибка чтения кэша: {e}")

    # 2. Получение настроек и истории
    # ... (без изменений) ...
    mode = 'friendly'; history_context = ''
    try:
        async with db.execute("SELECT mode FROM gemini_settings WHERE chat_id = ?", (chat_id,)) as cursor:
            mode_result = await cursor.fetchone(); mode = mode_result[0] if mode_result else mode
        async with db.execute("SELECT question, answer FROM gemini_conversations WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 5", (chat_id,)) as cursor:
            history = await cursor.fetchall()
            if history: history_context = "\n".join([f"User: {q}\nAI: {re.sub('<[^>]*>', '', a)}" for q, a in reversed(history)])
    except aiosqlite.Error as e: logger.error(f"Ошибка получения настроек/истории: {e}")

    # 3. Формирование промпта
    # ... (без изменений) ...
    project_context = await load_project_context()
    mode_prompts = {"formal": "Отвечай формально...", "friendly": "Отвечай дружелюбно...", "sarcastic": "Отвечай с сарказмом..."}
    prompt = f"{project_context}\n\nТы — SwiftDevBot...\nСтиль: {mode_prompts.get(mode, mode_prompts['friendly'])}\n\nДиалог:\n{history_context}\n\n---\nВопрос:\n{question}".strip()


    # 4. Запрос к API Gemini
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}" # Используем дешифрованный ключ
    payload = { # ... (payload как был) ...
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "topK": 10, "topP": 0.95, "maxOutputTokens": 2048},
        "safetySettings": [{"category": c, "threshold": "BLOCK_MEDIUM_AND_ABOVE"} for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]
    }
    max_retries = 2; base_delay = 1.5
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        for attempt in range(max_retries):
            try:
                logger.info(f"-> Gemini [Поп. {attempt+1}/{max_retries}]: '{question[:50]}...'")
                async with session.post(url, json=payload) as response:
                    # ... (логика обработки ответа, ретраев, ошибок - без изменений) ...
                    if response.status == 200:
                        try:
                            result = await response.json()
                            if result.get("candidates") and result["candidates"][0].get("content", {}).get("parts"):
                                raw_answer = result["candidates"][0]["content"]["parts"][0]["text"]
                                formatted_answer = format_response(raw_answer)
                                full_answer = f"<b>🤖 SwiftDevBot:</b>\n\n{formatted_answer}" # Заголовок ДО кэша
                                try: # Сохраняем в БД
                                     await db.execute("INSERT OR REPLACE INTO gemini_cache (question, answer) VALUES (?, ?)", (question, full_answer))
                                     await db.execute("INSERT INTO gemini_conversations (chat_id, question, answer) VALUES (?, ?, ?)", (chat_id, question, full_answer))
                                     await db.commit()
                                except aiosqlite.Error as db_e: logger.error(f"Ошибка сохранения ответа Gemini: {db_e}")
                                logger.info(f"<- Ответ Gemini получен для '{question[:50]}...'")
                                return full_answer
                            else: # Ответ 200, но нет кандидата
                                reason = result.get("promptFeedback", {}).get("blockReason", "Неизвестно")
                                logger.warning(f"Нет кандидата от Gemini. Причина: {reason}."); return f"❌ Ответ не сгенерирован (Фильтр: {reason})."
                        except (aiohttp.ContentTypeError, json.JSONDecodeError) as json_err: logger.error(f"Ошибка JSON Gemini: {json_err}"); return "❌ Ошибка обработки ответа ИИ."
                    elif response.status in [429, 500, 503] and attempt < max_retries - 1: # Ошибки сервера/лимиты
                        delay = base_delay * (2 ** attempt); logger.warning(f"Gemini {response.status}. Повтор через {delay:.1f} сек..."); await asyncio.sleep(delay); continue
                    else: # Другие ошибки
                        err_text = await response.text(); logger.error(f"Ошибка Gemini {response.status}: {err_text[:500]}"); msg = "❌ Ошибка ИИ.";
                        if response.status == 400: msg = "❌ Ошибка запроса (API ключ?)."; elif response.status == 429: msg = "❌ Лимит запросов."; elif response.status >= 500: msg = "❌ Ошибка сервера ИИ."; return msg
            except asyncio.TimeoutError: logger.error(f"Таймаут Gemini (Поп. {attempt + 1})"); if attempt < max_retries - 1: await asyncio.sleep(base_delay); continue; else: return "❌ ИИ не ответил вовремя."
            except aiohttp.ClientError as e: logger.error(f"Ошибка сети Gemini (Поп. {attempt + 1}): {e}"); if attempt < max_retries - 1: await asyncio.sleep(base_delay); continue; else: return "❌ Ошибка сети ИИ."
            except Exception as e: logger.error(f"Ошибка ask_gemini (Поп. {attempt + 1}): {e}", exc_info=True); 
            if attempt < max_retries - 1: await asyncio.sleep(base_delay); continue; else: return "❌ Внутренняя ошибка ИИ."
        return "❌ ИИ не отвечает после нескольких попыток." # Если все ретраи не удались

# --- Обработчики сообщений ---
@router.message(F.text & ~F.text.startswith('/') & (F.text.len() >= 3) & F.chat.type == "private")
async def handle_message(message: types.Message, kernel_data: dict):
    """Обработка текстовых сообщений как вопросов к Gemini."""
    db = kernel_data.get("db"); bot_ = kernel_data.get("bot")
    if db is None or bot_ is None: await message.reply("❌ Ошибка: Сервис временно недоступен."); return

    chat_id = message.chat.id; user_id = message.from_user.id; question = message.text
    rate_limit_seconds = 5; now = datetime.now(timezone.utc)
    try:
        async with db.execute("SELECT last_request FROM gemini_rate_limit WHERE chat_id = ?", (chat_id,)) as cursor: last_req_data = await cursor.fetchone()
        if last_req_data: last_req_time = datetime.fromisoformat(last_req_data[0]).replace(tzinfo=timezone.utc);
        if (now - last_req_time) < timedelta(seconds=rate_limit_seconds): await message.reply(f"⏳ Подожди {rate_limit_seconds} сек."); return
    except (aiosqlite.Error, ValueError) as e: logger.error(f"Ошибка rate limit {chat_id}: {e}")

    await bot_.send_chat_action(chat_id=chat_id, action="typing")
    answer = await ask_gemini(kernel_data, question, chat_id)
    await _reply_with_fallback(message, answer)
    try: await db.execute("INSERT OR REPLACE INTO gemini_rate_limit (chat_id, last_request) VALUES (?, ?)", (chat_id, now.isoformat())); await db.commit()
    except aiosqlite.Error as e: logger.error(f"Ошибка обновления rate limit {chat_id}: {e}")
    logger.info(f"🤖 Вопрос от {user_id}: '{question[:50]}...'")


# --- Обработчики команд ---
@router.message(Command("mode"))
async def mode_command(message: types.Message, command: CommandObject, kernel_data: dict):
    """Смена режима общения ИИ."""
    db = kernel_data.get("db");
    if db is None: await message.reply("❌ Ошибка: БД недоступна."); return

    new_mode = command.args.strip().lower() if command.args else None
    valid_modes = ["formal", "friendly", "sarcastic"]
    chat_id = message.chat.id

    if not new_mode: # Показываем текущий режим
        current_mode = 'friendly'
        try: async with db.execute("SELECT mode FROM gemini_settings WHERE chat_id = ?", (chat_id,)) as c: mode_res = await c.fetchone(); current_mode = mode_res[0] if mode_res else current_mode
        except aiosqlite.Error as e: logger.error(f"Ошибка получения режима {chat_id}: {e}"); await message.reply("❌ Ошибка получения режима."); return
        await message.reply(f"ℹ️ Текущий: `{current_mode}`.\nДоступные: {', '.join([f'`{m}`' for m in valid_modes])}\nИспользуйте: `/mode [режим]`", parse_mode="Markdown")
        return

    if new_mode not in valid_modes: await message.reply(f"❌ Неверный режим. Доступны: {', '.join([f'`{m}`' for m in valid_modes])}", parse_mode="Markdown"); return

    try: await db.execute("INSERT OR REPLACE INTO gemini_settings (chat_id, mode) VALUES (?, ?)", (chat_id, new_mode)); await db.commit()
    except aiosqlite.Error as e: logger.error(f"Ошибка смены режима: {e}"); await message.reply("❌ Ошибка сохранения режима."); return
    await message.reply(f"✅ Режим ИИ изменён на: `{new_mode}`", parse_mode="Markdown")
    logger.info(f"Режим для {message.from_user.id} изменён на {new_mode}")


@router.message(Command("clearcache"))
async def clear_cache_command(message: types.Message, kernel_data: dict):
    """Очистка кэша и истории GeminiAI (админ)."""
    if message.from_user.id not in kernel_data.get("admin_ids", []): await message.reply("🚫 Нет доступа!"); return
    db = kernel_data.get("db");
    if db is None: await message.reply("❌ Ошибка: БД недоступна."); return
    try:
        async with db.execute("SELECT COUNT(*) FROM gemini_cache") as c1: cache_count = (await c1.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM gemini_conversations") as c2: conv_count = (await c2.fetchone())[0]
        await db.execute("DELETE FROM gemini_cache"); await db.execute("DELETE FROM gemini_conversations"); await db.commit()
        await message.reply(f"🧹 Кэш (`{cache_count}`) и история (`{conv_count}`) GeminiAI очищены.", parse_mode="Markdown")
        logger.info(f"Кэш/история GeminiAI очищены админом {message.from_user.id}")
    except aiosqlite.Error as e: logger.error(f"Ошибка очистки GeminiAI: {e}"); await message.reply(f"❌ Ошибка: `{e}`")

# --- Обработчики для настройки ключа API через /sysconf ---

# Обработчик нажатия кнопки "Установить ключ" в /sysconf
@router.callback_query(F.data == "gemini:set_key")
async def set_key_start(callback: types.CallbackQuery, state: FSMContext, kernel_data: dict):
    # Проверяем, доступно ли шифрование
    if not CRYPTOGRAPHY_AVAILABLE: await callback.answer("Ошибка: Библиотека cryptography не установлена!", show_alert=True); return
    if not kernel_data.get("encryption_key"): await callback.answer("Ошибка: Ключ шифрования не настроен в боте!", show_alert=True); return

    await callback.message.edit_text("🔑 Введите Google Gemini API ключ.\n"
                                     "_(Сообщение с ключом будет удалено)_",
                                     reply_markup=None, parse_mode="Markdown")
    await state.set_state(GeminiAIStates.waiting_for_api_key)
    await callback.answer()

# Обработчик получения ключа в состоянии FSM
@router.message(GeminiAIStates.waiting_for_api_key, F.text)
async def process_api_key(message: types.Message, state: FSMContext, kernel_data: dict):
    api_key = message.text.strip()
    original_message_id = message.message_id # Запоминаем ID для удаления
    try: await message.delete() # Сразу удаляем сообщение с ключом
    except Exception as e: logger.warning(f"Не удалось удалить сообщение с ключом: {e}")

    if not api_key or len(api_key) < 10: # Простая проверка длины
         # Отправляем новое сообщение об ошибке
         await message.answer("❌ Ключ не похож на настоящий. Попробуйте снова или /cancel.", reply_markup=cancel_kb)
         return # Остаемся в состоянии

    fernet = kernel_data.get("encryption_key")
    # Дополнительная проверка fernet (хотя она есть и в set_key_start)
    if not fernet:
         await message.answer("❌ Ошибка: Ключ шифрования не настроен.", reply_markup=ReplyKeyboardRemove())
         await state.clear(); return

    try:
        encrypted_key = fernet.encrypt(api_key.encode()).decode()
        config_path = os.path.join(kernel_data["base_dir"], "data", "config.json")
        config = kernel_data["config"]
        config.setdefault("module_secrets", {})["gemini_ai"] = encrypted_key

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        logger.info(f"Ключ GeminiAI сохранен (зашифрован) админом {message.from_user.id}")
        # Отправляем новое сообщение об успехе
        await message.answer("✅ API ключ Gemini успешно сохранен и зашифрован.", reply_markup=ReplyKeyboardRemove())

        # Важно: После изменения конфига, нужно его как-то перезагрузить или обновить в kernel_data,
        # чтобы другие части бота (например, следующий вызов ask_gemini) использовали новый ключ.
        # Простой вариант - просто обновить в текущем kernel_data:
        kernel_data["config"] = config
        logger.info("Конфигурация в kernel_data обновлена.")

    except (OSError, TypeError, json.JSONDecodeError) as e:
        logger.error(f"Не удалось сохранить config.json с ключом Gemini: {e}")
        await message.answer("❌ Не удалось сохранить ключ в конфигурации.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        logger.error(f"Ошибка шифрования/сохранения ключа Gemini: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке ключа.", reply_markup=ReplyKeyboardRemove())

    await state.clear()

# Обработчик нетекстового сообщения при ожидании ключа
@router.message(GeminiAIStates.waiting_for_api_key)
async def process_api_key_wrong(message: types.Message):
    try: await message.delete()
    except Exception: pass
    await message.answer("Пожалуйста, отправьте API ключ текстом или /cancel.", reply_markup=cancel_kb)

# Обработчик команды /cancel в состоянии ожидания ключа
@router.message(Command("cancel"), StateFilter(GeminiAIStates.waiting_for_api_key))
async def cancel_key_handler(message: types.Message, state: FSMContext):
    logger.info(f"Пользователь {message.from_user.id} отменил ввод ключа Gemini.")
    await state.clear()
    await message.answer("Ввод ключа отменен.", reply_markup=ReplyKeyboardRemove())
    # Можно вернуть пользователя в меню настроек sys_conf, но это сложнее координировать
    # await message.answer("Возврат в главное меню...", reply_markup=ReplyKeyboardRemove()) # Пример


# --- Функции жизненного цикла модуля ---
def setup(kernel_data: dict):
    """Настройка модуля GeminiAI."""
    global CONTEXT_PATH
    base_dir = kernel_data.get("base_dir", ".")
    CONTEXT_PATH = os.path.join(base_dir, "data", "swiftdevbot_context.txt")

    # Проверка наличия cryptography
    if not CRYPTOGRAPHY_AVAILABLE:
        logger.error("❌ Библиотека 'cryptography' не найдена! Модуль GeminiAI не сможет работать с ключами API.")
        # Не регистрируем роутер, если нет библиотеки
        return

    # Настройка логгера (оставляем как было)
    log_dir = os.path.join(base_dir, "data"); os.makedirs(log_dir, exist_ok=True)
    module_log_path = os.path.join(log_dir, "gemini_ai.log")
    try:
        # Избегаем дублирования хендлера при перезапусках
        if not any(isinstance(h, RotatingFileHandler) and h.baseFilename == module_log_path for h in logger.handlers):
            log_handler = RotatingFileHandler(module_log_path, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
            log_handler.setLevel(logging.INFO); log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"); log_handler.setFormatter(log_formatter)
            logger.addHandler(log_handler)
        logger.info(f"Настроен лог-файл: {module_log_path}")
    except Exception as e: logger.error(f"Не удалось настроить логгер: {e}")

    dp = kernel_data.get("dp")
    if not dp: logger.critical("❌ Диспетчер не найден!"); return

    asyncio.create_task(init_db(kernel_data), name="gemini_ai_db_init")
    dp.include_router(router)
    logger.info("🛠 Модуль GeminiAI настроен.")

def get_commands() -> list[dict]:
    """Команды модуля."""
    return [
        {"command": "mode", "description": "Сменить режим ИИ", "admin": False, "icon": "🤖"},
        {"command": "clearcache", "description": "Очистить кэш ИИ", "admin": True, "icon": "🧹"}
    ]

def get_settings(kernel_data: dict) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    """Возвращает настройки модуля для /sysconf."""
    key_status = "❌ Не установлен"
    key_comment = "Ключ API необходим для работы модуля."
    if not CRYPTOGRAPHY_AVAILABLE:
         key_status = "⚠️ Шифрование недоступно!"
         key_comment = "Установите библиотеку `cryptography`."
    elif not kernel_data.get("encryption_key"):
         key_status = "⚠️ Ключ шифрования бота не настроен!"
         key_comment = "Добавьте `ENCRYPTION_KEY` в `.env` бота."
    else:
        encrypted_key = kernel_data.get("config", {}).get("module_secrets", {}).get("gemini_ai")
        if encrypted_key:
            key_status = "✅ Установлен (зашифрован)"
            key_comment = "Вы можете изменить ключ."
        else:
            key_comment += " Нажмите кнопку ниже, чтобы добавить."

    text = (
        f"🤖 **Модуль GeminiAI**\n"
        f"Статус API-ключа: {key_status}\n\n"
        f"{key_comment}\n\n"
        "Настройки режима общения доступны через команду `/mode`."
    )
    # Кнопку показываем только если шифрование доступно
    keyboard = None
    if CRYPTOGRAPHY_AVAILABLE and kernel_data.get("encryption_key"):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Установить/Изменить API ключ", callback_data="gemini:set_key")]
        ])
    return text, keyboard

async def on_startup(bot: Bot, data: dict):
    """Действия при запуске."""
    # Проверяем доступность ключа шифрования и API ключа
    if not CRYPTOGRAPHY_AVAILABLE:
         logger.error("❌ Cryptography не найден. GeminiAI не сможет использовать API ключ.")
    elif not data.get("encryption_key"):
         logger.warning("⚠️ Ключ шифрования бота не настроен. GeminiAI не сможет использовать API ключ.")
    elif not _get_decrypted_key(data): # Проверяем, установлен ли и дешифруется ли ключ
         logger.warning("⚠️ API ключ Gemini не установлен или не может быть дешифрован!")
         # Уведомляем админов один раз при старте
         admin_ids = data.get("admin_ids", [])
         msg = "⚠️ API ключ для **GeminiAI** не установлен или не может быть дешифрован. Установите его через `/sysconf`."
         tasks = [bot.send_message(aid, msg, parse_mode="Markdown") for aid in admin_ids]
         await asyncio.gather(*tasks, return_exceptions=True)
    else:
        logger.info("🚀 Модуль GeminiAI запущен с активным API ключом.")

    # Проверка black остается
    if not BLACK_AVAILABLE:
        logger.warning("⚠️ black не установлен. /format не работает.")
        # Уведомление админам об отсутствии black (можно объединить с проверкой ключа)


async def on_shutdown(bot: Bot, data: dict):
    """Действия при завершении."""
    logger.info("📴 Модуль GeminiAI завершает работу.")