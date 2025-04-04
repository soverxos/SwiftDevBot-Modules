# /modules/code_analyzer/module.py

import logging
from logging.handlers import RotatingFileHandler
import os
import asyncio # Добавлено для асинхронных операций
import aiosqlite # Замена sqlite3
import ast
import re
from datetime import datetime

from aiogram import Router, types, F
from aiogram.filters import Command

# Попробуем импортировать black, но сделаем его опциональным
try:
    import black
    BLACK_AVAILABLE = True
except ImportError:
    BLACK_AVAILABLE = False
    black = None # Явно указываем None, если black недоступен

# --- Логгер модуля ---
# Используем имя модуля для логгера
logger = logging.getLogger(__name__)
# Устанавливаем уровень DEBUG, если нужно ловить все сообщения отсюда,
# основной уровень фильтрации будет в ядре.
logger.setLevel(logging.DEBUG)

# Переменная для пути к БД, будет установлена в setup
DB_PATH = None

# --- Роутер модуля ---
router = Router()

# --- Инициализация БД ---
async def init_db(kernel_data: dict):
    """
    Инициализация базы данных модуля (создание таблицы).
    Вызывается асинхронно из setup.
    """
    global DB_PATH
    if DB_PATH is None:
         logger.error("❌ DB_PATH не установлен при асинхронной инициализации базы данных!")
         # В идеале, нужно уведомить админа или остановить запуск
         return

    db = kernel_data.get("db") # Получаем соединение из ядра
    if db is None:
        logger.error("❌ Не удалось получить соединение с БД из kernel_data для инициализации code_analyzer.db")
        return

    try:
        await db.execute('''CREATE TABLE IF NOT EXISTS analysis_history
                          (id INTEGER PRIMARY KEY AUTOINCREMENT,
                           chat_id INTEGER NOT NULL,
                           code TEXT,
                           result TEXT,
                           timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        # Индекс для быстрого поиска по chat_id
        await db.execute("CREATE INDEX IF NOT EXISTS idx_analysis_chat_id ON analysis_history (chat_id)")
        await db.commit()
        logger.info(f"📊 Таблица 'analysis_history' для CodeAnalyzer инициализирована в основной БД.")
    except aiosqlite.Error as e:
        logger.error(f"❌ Ошибка при инициализации таблицы 'analysis_history': {e}", exc_info=True)

# --- Функции работы с БД ---
async def save_analysis(kernel_data: dict, chat_id: int, code: str, result: str):
    """Сохранение результата анализа в базе данных (асинхронно)."""
    db = kernel_data.get("db")
    if db is None:
        logger.error("❌ Нет соединения с БД для сохранения анализа.")
        return

    try:
        async with db.execute("INSERT INTO analysis_history (chat_id, code, result) VALUES (?, ?, ?)",
                              (chat_id, code, result)) as cursor:
            pass # Выполнение запроса

        # Оставляем только последние N записей (например, 10)
        limit = 10
        async with db.execute("""
            DELETE FROM analysis_history
            WHERE chat_id = ? AND id NOT IN (
                SELECT id FROM analysis_history
                WHERE chat_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            )
        """, (chat_id, chat_id, limit)) as cursor:
             pass # Выполнение запроса

        await db.commit()
        logger.debug(f"💾 Сохранён результат анализа для chat_id {chat_id}")
    except aiosqlite.Error as e:
        logger.error(f"❌ Ошибка при сохранении анализа для chat_id {chat_id}: {e}", exc_info=True)

async def get_analysis_history(kernel_data: dict, chat_id: int) -> list:
    """Получение истории анализа для чата (асинхронно)."""
    db = kernel_data.get("db")
    if db is None:
        logger.error("❌ Нет соединения с БД для получения истории анализа.")
        return []

    try:
        async with db.execute("SELECT code, result, timestamp FROM analysis_history WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 5",
                              (chat_id,)) as cursor:
            history = await cursor.fetchall()
        return history
    except aiosqlite.Error as e:
        logger.error(f"❌ Ошибка при получении истории анализа для chat_id {chat_id}: {e}", exc_info=True)
        return []

async def clear_analysis_history(kernel_data: dict, chat_id: int) -> int:
    """Очистка истории анализа для чата (асинхронно). Возвращает количество удаленных строк."""
    db = kernel_data.get("db")
    if db is None:
        logger.error("❌ Нет соединения с БД для очистки истории анализа.")
        return 0

    try:
        # Сначала получаем количество строк для удаления (для информации)
        async with db.execute("SELECT COUNT(*) FROM analysis_history WHERE chat_id = ?", (chat_id,)) as cursor:
            count_result = await cursor.fetchone()
            count_to_delete = count_result[0] if count_result else 0

        if count_to_delete > 0:
            async with db.execute("DELETE FROM analysis_history WHERE chat_id = ?", (chat_id,)) as cursor:
                pass # Выполняем удаление
            await db.commit()
            logger.info(f"🗑️ История анализа очищена для chat_id {chat_id}. Удалено строк: {count_to_delete}")
            return count_to_delete
        else:
            logger.info(f"История анализа для chat_id {chat_id} уже пуста.")
            return 0
    except aiosqlite.Error as e:
        logger.error(f"❌ Ошибка при очистке истории для chat_id {chat_id}: {e}", exc_info=True)
        # Откатываем транзакцию, если что-то пошло не так (хотя commit выше)
        try: await db.rollback()
        except: pass
        raise e # Передаем ошибку дальше, чтобы ее можно было показать пользователю

# --- Основная логика модуля (синхронная) ---
def check_syntax(code):
    """Проверка синтаксиса Python-кода."""
    try:
        ast.parse(code)
        return True, "Синтаксис корректен ✅"
    except SyntaxError as e:
        # Улучшаем сообщение об ошибке
        error_line = e.text.strip() if e.text else "[строка не найдена]"
        return False, f"Синтаксическая ошибка: `{e.msg}` ❌\n" \
                      f"Строка: {e.lineno}, Позиция: {e.offset}\n" \
                      f"Код: `{error_line}`"

def analyze_code(code):
    """Анализ кода: проверка синтаксиса и рекомендации."""
    is_valid, syntax_result = check_syntax(code)
    recommendations = []

    # Простые проверки (можно расширить с помощью библиотек типа pylint/flake8, но это усложнит)
    if ".format(" in code and "f'" not in code and 'f"' not in code: # Проверяем, что не используются уже f-строки
        recommendations.append("Рекомендация: Рассмотрите использование f-строк (f'...' или f\"...\") вместо `.format()` для лучшей читаемости.")
    if re.search(r"print\s+\(", code): # Ищем 'print ('
        recommendations.append("Замечание: Пробел между `print` и скобкой `(` не соответствует PEP 8.")
    # Проверка на смешанные пробелы и табы (простая)
    lines = code.splitlines()
    has_tabs = any("\t" in line for line in lines)
    has_spaces_indent = any(line.startswith(" ") for line in lines)
    if has_tabs and has_spaces_indent:
         recommendations.append("Предупреждение: Обнаружено смешанное использование табов и пробелов для отступов. Рекомендуется использовать только пробелы (4 пробела на уровень).")
    elif has_tabs:
         recommendations.append("Замечание: Используются табы для отступов. PEP 8 рекомендует использовать пробелы.")

    # Формируем результат с использованием Markdown
    result = f"🔍 **Результат анализа кода:**\n\n" \
             f"**Синтаксис:** {syntax_result}\n\n" # syntax_result уже может содержать Markdown

    if recommendations:
        result += "**Рекомендации по улучшению:**\n" + "\n".join([f"• {rec}" for rec in recommendations]) # Используем маркеры списка
    elif is_valid: # Показываем только если синтаксис верен
        result += "**Рекомендации:** Код выглядит неплохо! 👍"
    else:
        result += "**Рекомендации:** Сначала исправьте синтаксические ошибки."

    return result

def format_code(code):
    """Форматирование кода с помощью black (синхронно)."""
    if not BLACK_AVAILABLE:
        logger.warning("Попытка форматирования без установленной библиотеки black.")
        return False, "❌ Форматирование недоступно: библиотека `black` не установлена."

    try:
        # Настройки форматирования можно изменить при необходимости
        mode = black.FileMode(line_length=88) # Стандартная длина строки для black
        formatted_code = black.format_str(code, mode=mode)
        if code == formatted_code:
             return True, (formatted_code, True) # Возвращаем кортеж: (код, флаг_без_изменений)
        else:
             return True, (formatted_code, False)
    except black.NothingChanged:
        # Эта ошибка может возникать, если код уже отформатирован
        return True, (code, True)
    except Exception as e:
        logger.error(f"Ошибка black при форматировании: {e}", exc_info=True)
        return False, f"❌ Ошибка при форматировании: `{str(e)}`"

# --- Обработчики команд ---
@router.message(Command("analyze"))
async def analyze_command(message: types.Message, kernel_data: dict):
    """Анализ переданного кода."""
    # Получаем код из сообщения
    code = message.text.replace(f"/{message.command}", "", 1).strip() # Убираем команду

    if not code:
        # Ищем код в ответе на сообщение
        if message.reply_to_message and message.reply_to_message.text:
            code = message.reply_to_message.text.strip()
            logger.info(f"Анализ кода из reply для {message.from_user.id}")
        elif message.reply_to_message and message.reply_to_message.caption:
             code = message.reply_to_message.caption.strip()
             logger.info(f"Анализ кода из caption reply для {message.from_user.id}")

    if not code:
        await message.reply("📝 **Как использовать:**\n"
                            "Напишите команду `/analyze` и после неё ваш Python код.\n"
                            "Или ответьте командой `/analyze` на сообщение с кодом.",
                            parse_mode="Markdown")
        return

    # Убираем возможные ```python ... ``` или ``` ... ```
    code = re.sub(r"^```(?:python)?\s*", "", code, flags=re.IGNORECASE)
    code = re.sub(r"\s*```$", "", code)
    code = code.strip()

    if not code:
         await message.reply("📝 Обнаружен пустой код после удаления обрамления ```.")
         return

    # Анализ кода (синхронная функция)
    analysis_result = analyze_code(code)

    # Сохранение в БД (асинхронно)
    await save_analysis(kernel_data, message.chat.id, code, analysis_result)

    # Получение истории (асинхронно)
    history = await get_analysis_history(kernel_data, message.chat.id)
    history_text = ""
    if history:
        history_text = "\n\n⏳ **Последние анализы (до 5):**\n"
        for idx, (hist_code, _, timestamp_str) in enumerate(history, 1):
             try:
                  # Попробуем распарсить timestamp для красивого вывода
                  dt_obj = datetime.fromisoformat(timestamp_str)
                  ts_formatted = dt_obj.strftime('%d.%m %H:%M')
             except:
                  ts_formatted = timestamp_str # Fallback
             # Показываем только начало кода
             code_preview = hist_code.split('\n', 1)[0][:50] # Первая строка или 50 символов
             history_text += f"`{idx}`. `{code_preview}...` ({ts_formatted})\n"

    # Отправляем результат
    try:
        await message.reply(
            f"{analysis_result}{history_text}",
            parse_mode="Markdown" # Используем Markdown для форматирования
        )
    except TelegramBadRequest as e:
         # Если ошибка парсинга Markdown из-за результата анализа
         if "can't parse entities" in str(e):
             logger.warning(f"Ошибка Markdown при отправке результата анализа: {e}")
             await message.reply(f"{analysis_result}{history_text}", parse_mode=None) # Отправляем без Markdown
         else:
             logger.error(f"Ошибка отправки результата анализа: {e}")
             await message.reply("❌ Произошла ошибка при отправке результата анализа.")

    logger.info(f"🔍 Код проанализирован для {message.from_user.id}: {code[:50]}...")

    # Подсчёт статистики (опционально, если модуль infosystem есть)
    loaded_mods = get_loaded_modules()
    if 'infosystem' in loaded_mods and hasattr(loaded_mods['infosystem'], 'increment_stat'):
        try:
            # Вызываем функцию статистики из другого модуля
            await loaded_mods['infosystem'].increment_stat(kernel_data, "code_analyzed")
        except Exception as stat_e:
            logger.error(f"Ошибка вызова статистики из infosystem: {stat_e}")


@router.message(Command("format"))
async def format_command(message: types.Message, kernel_data: dict):
    """Форматирование переданного кода."""
    if not BLACK_AVAILABLE:
        await message.reply("❌ Форматирование недоступно: библиотека `black` не установлена на сервере.", parse_mode='Markdown')
        return

    code = message.text.replace(f"/{message.command}", "", 1).strip()

    if not code:
        if message.reply_to_message and message.reply_to_message.text:
            code = message.reply_to_message.text.strip()
            logger.info(f"Форматирование кода из reply для {message.from_user.id}")
        elif message.reply_to_message and message.reply_to_message.caption:
             code = message.reply_to_message.caption.strip()
             logger.info(f"Форматирование кода из caption reply для {message.from_user.id}")

    if not code:
        await message.reply("📝 **Как использовать:**\n"
                            "Напишите команду `/format` и после неё ваш Python код.\n"
                            "Или ответьте командой `/format` на сообщение с кодом.",
                            parse_mode="Markdown")
        return

    # Убираем ```
    code = re.sub(r"^```(?:python)?\s*", "", code, flags=re.IGNORECASE)
    code = re.sub(r"\s*```$", "", code)
    code = code.strip()

    if not code:
         await message.reply("📝 Обнаружен пустой код после удаления обрамления ```.")
         return

    # Форматирование кода (синхронная функция)
    success, format_result = format_code(code)

    if success:
        formatted_code, no_changes = format_result
        if no_changes:
             response_text = "✅ **Код уже идеально отформатирован!** 👍"
        else:
             # Используем Markdown для блока кода
             response_text = f"🖌️ **Отформатированный код:**\n```python\n{formatted_code}\n```"
        logger.info(f"🖌️ Код отформатирован для {message.from_user.id}: {code[:50]}...")
    else:
        # format_result содержит сообщение об ошибке (уже с Markdown)
        response_text = format_result
        logger.error(f"❌ Ошибка форматирования для {message.from_user.id}: {format_result}")

    try:
        await message.reply(response_text, parse_mode="Markdown")
    except TelegramBadRequest as e:
         # Если ошибка парсинга (маловероятно для ```python)
         if "can't parse entities" in str(e):
             logger.warning(f"Ошибка Markdown при отправке результата форматирования: {e}")
             # Попытка отправить без Markdown, но код будет выглядеть плохо
             await message.reply(response_text.replace("```python", "").replace("```", ""), parse_mode=None)
         else:
             logger.error(f"Ошибка отправки результата форматирования: {e}")
             await message.reply("❌ Произошла ошибка при отправке результата форматирования.")

    # Статистика (опционально)
    loaded_mods = get_loaded_modules()
    if 'infosystem' in loaded_mods and hasattr(loaded_mods['infosystem'], 'increment_stat'):
        try:
            await loaded_mods['infosystem'].increment_stat(kernel_data, "code_formatted")
        except Exception as stat_e:
            logger.error(f"Ошибка вызова статистики из infosystem: {stat_e}")


@router.message(Command("clear_analysis"))
async def clear_analysis_command(message: types.Message, kernel_data: dict):
    """Очистка истории анализа для указанного чата (для админов)."""
    # Проверка прав доступа через kernel_data
    if message.from_user.id not in kernel_data.get("admin_ids", []):
        await message.reply("🚫 У вас нет доступа к этой команде!")
        logger.info(f"⛔ Доступ к /clear_analysis запрещён для {message.from_user.id}")
        return

    args = message.text.split(maxsplit=1)
    target_chat_id = None

    if len(args) >= 2:
        try:
            target_chat_id = int(args[1])
        except ValueError:
            await message.reply("📝 ID чата должен быть числом! `/clear_analysis [chat_id]`", parse_mode="Markdown")
            return
    else:
        # Если ID не указан, очищаем для текущего чата
        target_chat_id = message.chat.id
        logger.info(f"Админ {message.from_user.id} инициировал очистку истории для текущего чата ({target_chat_id})")

    try:
        deleted_count = await clear_analysis_history(kernel_data, target_chat_id)
        if deleted_count > 0:
            await message.reply(f"🗑️ Удалено `{deleted_count}` записей из истории анализа для чата `{target_chat_id}`.", parse_mode="Markdown")
        else:
             await message.reply(f"ℹ️ История анализа для чата `{target_chat_id}` уже была пуста.", parse_mode="Markdown")
    except Exception as e:
        # Ошибка уже залогирована в clear_analysis_history
        await message.reply(f"❌ Произошла ошибка при очистке истории: `{str(e)}`", parse_mode="Markdown")

    # Статистика (опционально)
    loaded_mods = get_loaded_modules()
    if 'infosystem' in loaded_mods and hasattr(loaded_mods['infosystem'], 'increment_stat'):
        try:
            await loaded_mods['infosystem'].increment_stat(kernel_data, "history_cleared")
        except Exception as stat_e:
            logger.error(f"Ошибка вызова статистики из infosystem: {stat_e}")

# --- Функции жизненного цикла модуля ---

def setup(kernel_data: dict):
    """Настройка модуля CodeAnalyzer."""
    global DB_PATH # Устанавливаем глобальную переменную для этого модуля

    # Настройка отдельного лог-файла для модуля
    base_dir = kernel_data.get("base_dir", ".") # Получаем базовую директорию
    log_dir = os.path.join(base_dir, "data")
    os.makedirs(log_dir, exist_ok=True) # Убеждаемся, что папка data существует
    module_log_path = os.path.join(log_dir, "code_analyzer.log")

    try:
        log_handler = RotatingFileHandler(
            module_log_path,
            maxBytes=5*1024*1024,  # 5 MB
            backupCount=3,         # 3 резервных копий
            encoding="utf-8"
        )
        log_handler.setLevel(logging.INFO) # Уровень для файла логов модуля
        log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        log_handler.setFormatter(log_formatter)
        # Добавляем обработчик к логгеру модуля
        logger.addHandler(log_handler)
        # Убираем передачу сообщений родительскому логгеру, чтобы не дублировать в основной лог
        # logger.propagate = False # Раскомментировать, если не хотите видеть логи модуля в общем логе
        logger.info(f"Настроен отдельный лог-файл модуля: {module_log_path}")
    except Exception as e:
        logger.error(f"Не удалось настроить файловый логгер для code_analyzer: {e}")

    # Получаем главный диспетчер
    dp = kernel_data.get("dp")
    if not dp:
         logger.critical("❌ Диспетчер (dp) не найден в kernel_data при настройке code_analyzer!")
         return # Не можем продолжить без диспетчера

    # Устанавливаем путь к основной БД (используем ее же)
    DB_PATH = os.path.join(kernel_data["base_dir"], "data", "database.db")
    logger.info(f"📂 Модуль будет использовать основную БД: {DB_PATH}")

    # Запускаем асинхронную инициализацию таблицы в фоне
    # create_task гарантирует, что setup не будет ждать завершения init_db
    init_task = asyncio.create_task(init_db(kernel_data))
    # Можно сохранить задачу, если нужно дождаться ее завершения где-то еще
    # kernel_data.setdefault("module_init_tasks", {})["code_analyzer"] = init_task

    # Регистрируем роутер модуля
    dp.include_router(router)

    logger.info("🛠 Модуль CodeAnalyzer настроен и роутер включен.")

def get_commands() -> list[dict]:
    """Список команд модуля CodeAnalyzer для CommandRegistry."""
    return [
        {
            "command": "analyze",
            "description": "Анализ кода Python", # Убрали иконку из описания
            "admin": False,
            "icon": "🔍" # Иконка указывается здесь
        },
        {
            "command": "format",
            "description": "Форматирование кода Python",
            "admin": False,
            "icon": "🖌️"
        },
        {
            "command": "clear_analysis",
            "description": "Очистка истории анализа",
            "admin": True, # Команда только для админов
            "icon": "🗑️"
        }
    ]

async def on_startup(bot, data: dict):
    """Действия при запуске модуля."""
    logger.info("🚀 Модуль CodeAnalyzer запущен.")
    if not BLACK_AVAILABLE:
        # Отправляем уведомление админам, если black не доступен
        admin_ids = data.get("admin_ids", [])
        for admin_id in admin_ids:
             try:
                  await bot.send_message(admin_id, "⚠️ Модуль CodeAnalyzer: библиотека `black` не найдена. Команда `/format` не будет работать.")
             except Exception as e:
                  logger.warning(f"Не удалось отправить уведомление админу {admin_id} об отсутствии black: {e}")
        logger.warning("⚠️ Библиотека black не установлена. Команда /format не будет работать.")

async def on_shutdown(bot, data: dict):
    """Действия при завершении работы модуля."""
    # Здесь можно закрыть специфичные ресурсы модуля, если они есть
    # Например, если бы мы использовали отдельное соединение с БД для модуля:
    # if module_db_connection:
    #    await module_db_connection.close()
    logger.info("📴 Модуль CodeAnalyzer завершает работу.")

# --- Дополнительно: Регистрация фоновой задачи (если нужна) ---
# async def my_code_analyzer_task(kernel_data):
#     while True:
#         # ... do something ...
#         await asyncio.sleep(3600) # Например, раз в час

# Нужно добавить регистрацию в setup:
# def setup(kernel_data: dict):
#     # ... (остальной код setup) ...
#     if "background_tasks" in kernel_data:
#         kernel_data["background_tasks"].append(my_code_analyzer_task)
#         logger.info("Фоновая задача my_code_analyzer_task зарегистрирована.")