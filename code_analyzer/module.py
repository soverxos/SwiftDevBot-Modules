# /modules/code_analyzer/module.py

import logging
from logging.handlers import RotatingFileHandler
import os
import asyncio
import aiosqlite
import ast
import re
from datetime import datetime
from typing import List, Tuple, Any # Добавлен Type Hinting

from aiogram import Router, types, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.filters.command import CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

# Импорт функции ядра больше не нужен, т.к. убрали infosystem
# from core.modules import get_loaded_modules

# Попробуем импортировать black
try:
    import black
    BLACK_AVAILABLE = True
except ImportError:
    BLACK_AVAILABLE = False
    black = None

# --- Логгер модуля ---
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG) # Уровень DEBUG для подробного логгирования модуля

# --- Роутер модуля ---
router = Router()

# --- Состояния FSM ---
class CodeInputStates(StatesGroup):
    waiting_for_analyze_code = State()
    waiting_for_format_code = State()

# --- Кнопка Отмены для FSM ---
cancel_button = KeyboardButton(text="/cancel")
cancel_kb = ReplyKeyboardMarkup(keyboard=[[cancel_button]], resize_keyboard=True, one_time_keyboard=True) # Добавлен one_time_keyboard

# --- Инициализация БД ---
async def init_db(kernel_data: dict):
    """Инициализация таблицы 'analysis_history' в основной БД."""
    db = kernel_data.get("db")
    if db is None: logger.error("❌ БД недоступна для инициализации"); return
    try:
        await db.execute('''CREATE TABLE IF NOT EXISTS analysis_history
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, code TEXT,
                           result TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute("CREATE INDEX IF NOT EXISTS idx_analysis_chat_id ON analysis_history (chat_id)")
        await db.commit()
        logger.info("📊 Таблица 'analysis_history' инициализирована.")
    except aiosqlite.Error as e: logger.error(f"❌ Ошибка init_db: {e}", exc_info=True)

# --- Функции работы с БД (асинхронные) ---
async def save_analysis(kernel_data: dict, chat_id: int, code: str, result: str):
    db = kernel_data.get("db")
    if db is None: logger.error("❌ БД недоступна для сохранения"); return
    try:
        await db.execute("INSERT INTO analysis_history (chat_id, code, result) VALUES (?, ?, ?)", (chat_id, code, result))
        limit = 10
        await db.execute("DELETE FROM analysis_history WHERE chat_id = ? AND id NOT IN (SELECT id FROM analysis_history WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?)", (chat_id, chat_id, limit))
        await db.commit()
        logger.debug(f"💾 Сохранён анализ для chat_id {chat_id}")
    except aiosqlite.Error as e: logger.error(f"❌ Ошибка save_analysis: {e}", exc_info=True)

async def get_analysis_history(kernel_data: dict, chat_id: int) -> List[Tuple[Any, ...]]:
    db = kernel_data.get("db")
    if db is None: logger.error("❌ БД недоступна для истории"); return []
    try:
        async with db.execute("SELECT code, result, timestamp FROM analysis_history WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 5", (chat_id,)) as cursor:
            return await cursor.fetchall() # cursor.fetchall() возвращает list[tuple]
    except aiosqlite.Error as e: logger.error(f"❌ Ошибка get_history: {e}", exc_info=True); return []

async def clear_analysis_history(kernel_data: dict, chat_id: int) -> int:
    db = kernel_data.get("db")
    if db is None: logger.error("❌ БД недоступна для очистки"); return 0
    try:
        async with db.execute("SELECT COUNT(*) FROM analysis_history WHERE chat_id = ?", (chat_id,)) as cursor:
            count_result = await cursor.fetchone(); count_to_delete = count_result[0] if count_result else 0
        if count_to_delete > 0:
            await db.execute("DELETE FROM analysis_history WHERE chat_id = ?", (chat_id,)); await db.commit()
            logger.info(f"🗑️ История очищена для chat_id {chat_id}. Удалено: {count_to_delete}")
            return count_to_delete
        else: logger.info(f"История для chat_id {chat_id} пуста."); return 0
    except aiosqlite.Error as e:
        # Упрощенная обработка ошибки - просто логируем и передаем дальше
        logger.error(f"❌ Ошибка clear_history для chat_id {chat_id}: {e}", exc_info=True)
        raise e # Передаем ошибку для отображения пользователю

# --- Вспомогательные функции ---
def _preprocess_code(code: str | None) -> tuple[str | None, bool]:
    """Удаляет ```, заменяет \u00A0 на пробел."""
    if not code: return None, False
    original_code = code
    processed_code = re.sub(r"^```(?:python)?\s*|\s*```$", "", code, flags=re.I).strip()
    processed_code = processed_code.replace('\u00A0', ' ')
    was_fixed = original_code != processed_code and '\u00A0' in original_code
    return processed_code if processed_code else None, was_fixed

def _format_history(history: list) -> str:
    """Форматирует список истории анализа для вывода."""
    if not history: return ""
    history_text = "\n\n⏳ **Последние анализы:**\n"
    for idx, (hist_code, _, timestamp_str) in enumerate(history, 1):
         try: dt_obj = datetime.fromisoformat(timestamp_str); ts_formatted = dt_obj.strftime('%d.%m %H:%M')
         except: ts_formatted = timestamp_str # Fallback
         code_preview = hist_code.split('\n', 1)[0][:60] # Немного увеличим превью
         history_text += f"`{idx}`. `{code_preview}...` ({ts_formatted})\n"
    return history_text

async def _reply_with_fallback(message: types.Message, text: str, **kwargs):
     """Отправляет ответ, пытаясь с Markdown, при ошибке - без."""
     try:
         await message.reply(text, parse_mode="Markdown", **kwargs)
     except TelegramBadRequest as e:
         if "can't parse entities" in str(e):
             logger.warning(f"Ошибка Markdown: {e}. Попытка без форматирования.")
             # Убираем Markdown символы, которые могли вызвать ошибку
             safe_text = re.sub(r"[`*_~]", "", text) # Простая очистка
             await message.reply(safe_text, parse_mode=None, **kwargs)
         else:
             logger.error(f"Ошибка Telegram BadRequest при отправке: {e}")
             await message.reply(f"❌ Ошибка отправки ответа: {e.message}", **kwargs) # Показываем текст ошибки ТГ
     except Exception as e:
         logger.error(f"Неожиданная ошибка при отправке ответа: {e}", exc_info=True)
         await message.reply("❌ Произошла непредвиденная ошибка при отправке ответа.", **kwargs)


# --- Основная логика модуля (синхронная) ---
def check_syntax(code):
    """Проверка синтаксиса Python."""
    try: ast.parse(code); return True, "Синтаксис корректен ✅"
    except SyntaxError as e:
        error_line = e.text.strip() if e.text else "[строка не найдена]"
        return False, f"Синтаксическая ошибка: `{e.msg}` ❌\nСтрока: {e.lineno}, Поз.: {e.offset}\nКод: `{error_line}`"

def analyze_code(code):
    """Анализ кода Python."""
    is_valid, syntax_result = check_syntax(code)
    recommendations = []
    if is_valid:
        if ".format(" in code and "f'" not in code and 'f"' not in code: recommendations.append("Рассмотрите f-строки (f'...') вместо `.format()`.")
        if re.search(r"print\s+\(", code): recommendations.append("Пробел `print (` не по PEP 8.")
        lines = code.splitlines(); has_tabs = any("\t" in l for l in lines); has_spaces = any(l.startswith(" ") for l in lines)
        if has_tabs and has_spaces: recommendations.append("Смешанные табы/пробелы. Используйте пробелы.")
        elif has_tabs: recommendations.append("Табы вместо пробелов (PEP 8 рекомендует пробелы).")

    result = f"🔍 **Результат анализа:**\n\n**Синтаксис:** {syntax_result}\n\n"
    if recommendations: result += "**Рекомендации:**\n" + "\n".join([f"• {rec}" for rec in recommendations])
    elif is_valid: result += "**Рекомендации:** Код выглядит неплохо! 👍"
    else: result += "**Рекомендации:** Исправьте синтаксис."
    return result

def format_code(code):
    """Форматирование кода black."""
    if not BLACK_AVAILABLE: logger.warning("Попытка форматирования без black."); return False, "❌ `black` не установлен."
    try:
        mode = black.FileMode(line_length=88); formatted = black.format_str(code, mode=mode)
        return True, (formatted, code == formatted)
    except black.NothingChanged: return True, (code, True)
    except Exception as e: logger.error(f"Ошибка black: {e}", exc_info=True); return False, f"❌ Ошибка: `{str(e)}`"

# --- Обработчик команды /cancel (для всех состояний этого модуля) ---
@router.message(Command("cancel"), StateFilter(CodeInputStates))
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    logger.info(f"Пользователь {message.from_user.id} отменил состояние {current_state}")
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())

# --- Обработчики команды /analyze ---
@router.message(Command("analyze"))
async def analyze_start(message: types.Message, command: CommandObject, state: FSMContext, kernel_data: dict):
    """Начало диалога для анализа кода или анализ из аргументов."""
    initial_code, _ = _preprocess_code(command.args)

    if initial_code:
        logger.info(f"Анализ кода из аргументов для {message.from_user.id}")
        await state.clear()
        analysis_result = analyze_code(initial_code)
        await save_analysis(kernel_data, message.chat.id, initial_code, analysis_result)
        history = await get_analysis_history(kernel_data, message.chat.id)
        history_text = _format_history(history) # Используем хелпер
        response_text = f"{analysis_result}{history_text}"
        await _reply_with_fallback(message, response_text) # Используем хелпер для ответа
        logger.info(f"🔍 Код из аргументов проанализирован для {message.from_user.id}")
    else:
        await message.answer("🐍 Отправьте Python код для анализа.\nИли /cancel для отмены.", reply_markup=cancel_kb)
        await state.set_state(CodeInputStates.waiting_for_analyze_code)
        logger.info(f"Состояние waiting_for_analyze_code установлено для {message.from_user.id}")

@router.message(CodeInputStates.waiting_for_analyze_code, F.text)
async def analyze_process_code(message: types.Message, state: FSMContext, kernel_data: dict):
    """Обработка кода, введенного пользователем в состоянии ожидания анализа."""
    logger.info(f"Получен код для анализа от {message.from_user.id}")
    processed_code, fixed = _preprocess_code(message.text)

    if not processed_code:
        await message.reply("Код пуст после обработки. Попробуйте снова или /cancel.", reply_markup=cancel_kb); return

    if fixed: await message.reply("ℹ️ *Исправлены невидимые символы.*", parse_mode="Markdown")

    analysis_result = analyze_code(processed_code)
    await save_analysis(kernel_data, message.chat.id, processed_code, analysis_result)
    history = await get_analysis_history(kernel_data, message.chat.id)
    history_text = _format_history(history) # Используем хелпер
    response_text = f"{analysis_result}{history_text}"

    await _reply_with_fallback(message, response_text, reply_markup=ReplyKeyboardRemove()) # Хелпер и убираем кнопку

    await state.clear(); logger.info(f"Состояние сброшено для {message.from_user.id} после анализа.")

@router.message(CodeInputStates.waiting_for_analyze_code)
async def analyze_wrong_content(message: types.Message):
    """Обработка нетекстового сообщения в состоянии ожидания анализа."""
    await message.reply("Пожалуйста, отправьте текст с кодом или /cancel.", reply_markup=cancel_kb)

# --- Обработчики команды /format ---
@router.message(Command("format"))
async def format_start(message: types.Message, command: CommandObject, state: FSMContext, kernel_data: dict):
    """Начало диалога для форматирования кода или форматирование из аргументов."""
    if not BLACK_AVAILABLE: await message.reply("❌ Форматирование (`black`) недоступно.", parse_mode='Markdown'); return

    initial_code, _ = _preprocess_code(command.args)

    if initial_code:
        logger.info(f"Форматирование кода из аргументов для {message.from_user.id}")
        await state.clear()
        success, format_result = format_code(initial_code)
        if success:
            formatted_code, no_changes = format_result
            if no_changes: response_text = "✅ **Код уже отформатирован!** 👍"
            else: response_text = f"🖌️ **Отформатированный код:**\n```python\n{formatted_code}\n```"
        else: response_text = format_result
        await _reply_with_fallback(message, response_text) # Используем хелпер
        logger.info(f"🖌️ Код из аргументов отформатирован для {message.from_user.id}")
    else:
        await message.answer("🖌️ Отправьте Python код для форматирования.\nИли /cancel.", reply_markup=cancel_kb)
        await state.set_state(CodeInputStates.waiting_for_format_code)
        logger.info(f"Состояние waiting_for_format_code установлено для {message.from_user.id}")

@router.message(CodeInputStates.waiting_for_format_code, F.text)
async def format_process_code(message: types.Message, state: FSMContext, kernel_data: dict):
    """Обработка кода, введенного пользователем в состоянии ожидания форматирования."""
    logger.info(f"Получен код для форматирования от {message.from_user.id}")
    processed_code, fixed = _preprocess_code(message.text)

    if not processed_code:
        await message.reply("Код пуст после обработки. Попробуйте снова или /cancel.", reply_markup=cancel_kb); return
    if fixed: await message.reply("ℹ️ *Исправлены невидимые символы.*", parse_mode="Markdown")

    success, format_result = format_code(processed_code)
    if success:
        formatted_code, no_changes = format_result
        if no_changes: response_text = "✅ **Код уже отформатирован!** 👍"
        else: response_text = f"🖌️ **Отформатированный код:**\n```python\n{formatted_code}\n```"
    else: response_text = format_result

    await _reply_with_fallback(message, response_text, reply_markup=ReplyKeyboardRemove()) # Хелпер и убираем кнопку
    await state.clear(); logger.info(f"Состояние сброшено для {message.from_user.id} после форматирования.")

@router.message(CodeInputStates.waiting_for_format_code)
async def format_wrong_content(message: types.Message):
    """Обработка нетекстового сообщения в состоянии ожидания форматирования."""
    await message.reply("Пожалуйста, отправьте текст с кодом или /cancel.", reply_markup=cancel_kb)

# --- Обработчик команды /clear_analysis (админская) ---
@router.message(Command("clear_analysis"))
async def clear_analysis_command(message: types.Message, command: CommandObject, kernel_data: dict):
    """Очистка истории анализа для чата (админ)."""
    if message.from_user.id not in kernel_data.get("admin_ids", []):
        await message.reply("🚫 У вас нет доступа!"); logger.info(f"⛔ Доступ /clear запрещён {message.from_user.id}"); return

    target_chat_id_str = command.args.strip() if command.args else None
    target_chat_id = None
    if target_chat_id_str:
        try: target_chat_id = int(target_chat_id_str)
        except ValueError: await message.reply("📝 ID чата - число! `/clear [ID]`", parse_mode="Markdown"); return
    else: target_chat_id = message.chat.id; logger.info(f"Админ {message.from_user.id} чистит историю для {target_chat_id}")

    try:
        deleted_count = await clear_analysis_history(kernel_data, target_chat_id)
        if deleted_count > 0: await message.reply(f"🗑️ Удалено записей: `{deleted_count}` для `{target_chat_id}`.", parse_mode="Markdown")
        else: await message.reply(f"ℹ️ История для `{target_chat_id}` пуста.", parse_mode="Markdown")
    except Exception as e: await message.reply(f"❌ Ошибка очистки: `{str(e)}`", parse_mode="Markdown")

# --- Функции жизненного цикла модуля ---
def setup(kernel_data: dict):
    """Настройка модуля CodeAnalyzer."""
    base_dir = kernel_data.get("base_dir", ".")
    log_dir = os.path.join(base_dir, "data"); os.makedirs(log_dir, exist_ok=True)
    module_log_path = os.path.join(log_dir, "code_analyzer.log")
    try:
        log_handler = RotatingFileHandler(module_log_path, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
        log_handler.setLevel(logging.INFO); log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"); log_handler.setFormatter(log_formatter)
        logger.addHandler(log_handler); logger.info(f"Настроен лог-файл: {module_log_path}")
    except Exception as e: logger.error(f"Не удалось настроить логгер: {e}")

    dp = kernel_data.get("dp")
    if not dp: logger.critical("❌ Диспетчер не найден!"); return

    asyncio.create_task(init_db(kernel_data), name="code_analyzer_db_init")
    dp.include_router(router)
    logger.info("🛠 Модуль CodeAnalyzer настроен.")

def get_commands() -> list[dict]:
    """Команды модуля."""
    return [
        {"command": "analyze", "description": "Анализ кода Python", "admin": False, "icon": "🔍"},
        {"command": "format", "description": "Форматирование кода Python", "admin": False, "icon": "🖌️"},
        {"command": "clear_analysis", "description": "Очистка истории анализа", "admin": True, "icon": "🗑️"}
    ]

async def on_startup(bot: Bot, data: dict):
    """Действия при запуске."""
    logger.info("🚀 Модуль CodeAnalyzer запущен.")
    if not BLACK_AVAILABLE:
        admin_ids = data.get("admin_ids", [])
        tasks = [bot.send_message(aid, "⚠️ `black` не найден. `/format` не работает.") for aid in admin_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for aid, res in zip(admin_ids, results):
            if isinstance(res, Exception): logger.warning(f"Не уведомил {aid} об отсутствии black: {res}")
        logger.warning("⚠️ black не установлен. /format не работает.")

async def on_shutdown(bot: Bot, data: dict):
    """Действия при завершении."""
    logger.info("📴 Модуль CodeAnalyzer завершает работу.")