from aiogram import Router, types
from aiogram.filters import Command
import logging
from logging.handlers import RotatingFileHandler
import os
import sqlite3
import ast
import re
from datetime import datetime
from core.modules import get_loaded_modules

# Попробуем импортировать black, но сделаем его опциональным
try:
    import black
    BLACK_AVAILABLE = True
except ImportError:
    BLACK_AVAILABLE = False
    black = None

router = Router()
logger = logging.getLogger("modules.code_analyzer")

# Настройка логов для модуля
log_handler = RotatingFileHandler(
    os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "data", "code_analyzer.log"),
    maxBytes=5*1024*1024,  # 5 MB максимальный размер файла
    backupCount=5,         # Хранить до 5 резервных копий
    encoding="utf-8"
)
log_handler.setLevel(logging.INFO)
log_formatter = logging.Formatter("%(asctime)s - %(message)s")
log_handler.setFormatter(log_formatter)
logger.addHandler(log_handler)
logger.setLevel(logging.INFO)

data = None
DB_PATH = None

def setup(d):
    """Настройка модуля CodeAnalyzer."""
    global data, DB_PATH
    dp = d["dp"]
    data = d
    DB_PATH = os.path.join(data["base_dir"], "data", "code_analyzer.db")
    logger.info(f"📂 DB_PATH установлен: {DB_PATH}")
    init_db()
    dp.include_router(router)
    logger.info("🛠 Модуль CodeAnalyzer настроен")

def init_db():
    """Инициализация базы данных для хранения истории анализа."""
    if DB_PATH is None:
        logger.error("❌ DB_PATH не установлен при инициализации базы данных!")
        raise ValueError("DB_PATH must be set before initializing the database")
    logger.info(f"📊 Инициализация базы данных: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS analysis_history 
                      (chat_id INTEGER, code TEXT, result TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()
    logger.info("📊 База данных для CodeAnalyzer инициализирована")

def get_commands():
    """Список команд модуля CodeAnalyzer."""
    return [
        types.BotCommand(command="analyze", description="🔍 Анализ кода (Python)"),
        types.BotCommand(command="format", description="🖌️ Форматирование кода (Python)"),
        types.BotCommand(command="clear_analysis", description="🗑️ Очистка истории анализа (админ)")
    ]

def save_analysis(chat_id, code, result):
    """Сохранение результата анализа в базе данных."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO analysis_history (chat_id, code, result) VALUES (?, ?, ?)", 
                       (chat_id, code, result))
        # Оставляем только последние 5 записей для каждого chat_id
        cursor.execute("""
            DELETE FROM analysis_history 
            WHERE chat_id = ? AND timestamp NOT IN (
                SELECT timestamp FROM analysis_history 
                WHERE chat_id = ? 
                ORDER BY timestamp DESC 
                LIMIT 5
            )
        """, (chat_id, chat_id))
        conn.commit()
        conn.close()
        logger.info(f"💾 Сохранён результат анализа для chat_id {chat_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении анализа для chat_id {chat_id}: {e}")

def get_analysis_history(chat_id):
    """Получение истории анализа для чата."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT code, result, timestamp FROM analysis_history WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 5", 
                       (chat_id,))
        history = cursor.fetchall()
        conn.close()
        return history
    except Exception as e:
        logger.error(f"❌ Ошибка при получении истории анализа для chat_id {chat_id}: {e}")
        return []

def check_syntax(code):
    """Проверка синтаксиса Python-кода."""
    try:
        ast.parse(code)
        return True, "Синтаксис корректен ✅"
    except SyntaxError as e:
        return False, f"Синтаксическая ошибка: {str(e)} ❌\n" \
                      f"Строка: {e.lineno}, позиция: {e.offset}"

def analyze_code(code):
    """Анализ кода: проверка синтаксиса и рекомендации."""
    # Проверка синтаксиса
    is_valid, syntax_result = check_syntax(code)
    recommendations = []

    # Базовые рекомендации
    if ".format(" in code:
        recommendations.append("Рекомендация: Вместо .format() используйте f-строки (f-strings) для лучшей читаемости. Например: f'Hello {name}' вместо 'Hello {}'.format(name).")
    if "print (" in code:
        recommendations.append("Замечание: В Python пробел после print не нужен, это не соответствует PEP 8. Правильно: print().")
    if "  " in code:
        recommendations.append("Замечание: Обнаружены лишние пробелы. Согласно PEP 8, используйте ровно один пробел между элементами.")
    if "if(" in code or "for(" in code:
        recommendations.append("Замечание: После ключевых слов (if, for и т.д.) должен быть пробел. Правильно: if (условие), а не if(условие).")

    # Формируем результат
    result = f"🔍 <b>Результат анализа кода:</b>\n\n" \
             f"<b>Синтаксис:</b> {syntax_result}\n\n"
    
    if recommendations:
        result += "<b>Рекомендации по улучшению:</b>\n" + "\n".join([f"- {rec}" for rec in recommendations])
    else:
        result += "<b>Рекомендации:</b> Код выглядит хорошо! 😊"

    return result

def format_code(code):
    """Форматирование кода с помощью black."""
    if not BLACK_AVAILABLE:
        return False, "❌ Форматирование недоступно: библиотека black не установлена. Установите её с помощью `pip install black`."
    
    try:
        formatted = black.format_str(code, mode=black.FileMode())
        return True, formatted
    except Exception as e:
        return False, f"❌ Ошибка при форматировании: {str(e)}"

@router.message(Command("analyze"))
async def analyze_command(message: types.Message):
    """Анализ переданного кода."""
    # Подсчёт статистики
    if 'infosystem' in get_loaded_modules():
        from modules.infosystem.module import increment_stat
        increment_stat("commands_executed")
    else:
        logger.warning("Модуль infosystem не загружен, пропускаем подсчёт статистики commands_executed")

    # Извлечение кода из сообщения
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("📝 Укажи код для анализа. Пример: <code>/analyze print('Hello')</code>", parse_mode="HTML")
        return
    
    code = args[1].strip()
    if not code:
        await message.answer("📝 Код не может быть пустым!", parse_mode="HTML")
        return

    # Анализ кода
    result = analyze_code(code)
    save_analysis(message.chat.id, code, result)

    # Добавляем историю анализа
    history = get_analysis_history(message.chat.id)
    history_text = "<b>Последние анализы (до 5):</b>\n"
    for idx, (hist_code, hist_result, timestamp) in enumerate(history, 1):
        history_text += f"{idx}. <code>{hist_code[:50]}...</code> ({timestamp})\n"

    # Отправляем результат
    await message.answer(
        f"{result}\n\n{history_text}",
        parse_mode="HTML"
    )
    logger.info(f"🔍 Код проанализирован для {message.from_user.id}: {code[:50]}...")

@router.message(Command("format"))
async def format_command(message: types.Message):
    """Форматирование переданного кода."""
    # Подсчёт статистики
    if 'infosystem' in get_loaded_modules():
        from modules.infosystem.module import increment_stat
        increment_stat("commands_executed")
    else:
        logger.warning("Модуль infosystem не загружен, пропускаем подсчёт статистики commands_executed")

    # Извлечение кода из сообщения
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("📝 Укажи код для форматирования. Пример: <code>/format print('Hello')</code>", parse_mode="HTML")
        return
    
    code = args[1].strip()
    if not code:
        await message.answer("📝 Код не может быть пустым!", parse_mode="HTML")
        return

    # Форматирование кода
    success, result = format_code(code)
    if success:
        formatted_code = result
        await message.answer(
            f"🖌️ <b>Отформатированный код:</b>\n\n<code>{formatted_code}</code>",
            parse_mode="HTML"
        )
        logger.info(f"🖌️ Код отформатирован для {message.from_user.id}: {code[:50]}...")
    else:
        await message.answer(result, parse_mode="HTML")
        logger.error(f"❌ Ошибка форматирования для {message.from_user.id}: {result}")

@router.message(Command("clear_analysis"))
async def clear_analysis_command(message: types.Message):
    """Очистка истории анализа для указанного чата (для админов)."""
    if message.from_user.id not in data["admin_ids"]:
        await message.answer("🚫 У вас нет доступа к этой команде!", parse_mode="HTML")
        logger.info(f"⛔ Доступ к /clear_analysis запрещён для {message.from_user.id}")
        return

    # Подсчёт статистики
    if 'infosystem' in get_loaded_modules():
        from modules.infosystem.module import increment_stat
        increment_stat("commands_executed")
    else:
        logger.warning("Модуль infosystem не загружен, пропускаем подсчёт статистики commands_executed")

    # Извлечение chat_id из команды
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("📝 Укажи chat_id для очистки. Пример: <code>/clear_analysis 123456789</code>", parse_mode="HTML")
        return
    
    try:
        chat_id = int(args[1])
    except ValueError:
        await message.answer("📝 chat_id должен быть числом!", parse_mode="HTML")
        return

    # Очистка истории
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM analysis_history WHERE chat_id = ?", (chat_id,))
        deleted = conn.total_changes
        conn.commit()
        conn.close()
        await message.answer(f"🗑️ Удалено <code>{deleted}</code> записей из истории анализа для chat_id {chat_id}.", parse_mode="HTML")
        logger.info(f"🗑️ История анализа очищена для chat_id {chat_id} администратором {message.from_user.id}")
    except Exception as e:
        await message.answer(f"❌ Ошибка при очистке истории: {str(e)}", parse_mode="HTML")
        logger.error(f"❌ Ошибка при очистке истории для chat_id {chat_id}: {e}")

async def on_startup(d):
    """Действия при запуске модуля."""
    logger.info("🚀 Модуль CodeAnalyzer запущен.")
    if not BLACK_AVAILABLE:
        logger.warning("⚠️ Библиотека black не установлена. Команда /format не будет работать.")

async def on_shutdown(d):
    """Действия при завершении работы модуля."""
    logger.info("📴 Модуль CodeAnalyzer завершает работу.")