# ./modules/<module_name>/module.py
import os
import json
import logging
import asyncio
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Настройка логирования
logger = logging.getLogger(__name__)

# Инициализация роутера
router = Router()

# Глобальная переменная для хранения данных ядра
_kernel_data = None

# Определение состояний FSM (если нужны)
class ModuleStates(StatesGroup):
    waiting_for_input = State()

# Метаданные модуля
DISPLAY_NAME = "Название модуля"  # Отображаемое имя
DESCRIPTION = "Описание модуля и его функций."
GLOBAL_PARAMETERS = {  # Глобальные настройки (для админов)
    "example_global_param": {
        "description": "Пример глобального параметра",
        "required": False,
        "default": "значение по умолчанию"
    }
}
USER_PARAMETERS = {  # Пользовательские настройки
    "example_user_param": {
        "description": "Пример пользовательского параметра",
        "required": False,
        "default": "значение по умолчанию"
    }
}

def setup(kernel_data):
    """Инициализация модуля при загрузке."""
    global _kernel_data
    _kernel_data = kernel_data
    dp = kernel_data["dp"]
    base_dir = kernel_data["base_dir"]
    dp.include_router(router)
    
    db = kernel_data.get("db")
    if db is None:
        logger.error("База данных не инициализирована в kernel_data['db']!")
        raise ValueError("База данных не инициализирована!")
    
    asyncio.create_task(init_db(db))
    init_config(base_dir)
    
    logger.info(f"Модуль {DISPLAY_NAME} успешно загружен и настроен")

async def init_db(db):
    """Инициализация таблицы для хранения пользовательских настроек."""
    module_name = __name__.split(".")[-2]  # Автоматическое определение имени модуля
    table_name = f"{module_name}_config"
    try:
        async with db.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'") as cursor:
            if not await cursor.fetchone():
                await db.execute(f"""
                    CREATE TABLE {table_name} (
                        user_id INTEGER PRIMARY KEY,
                        example_user_param TEXT
                    )
                """)
                await db.commit()
                logger.info(f"Таблица {table_name} создана")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")
        raise

def init_config(base_dir):
    """Инициализация конфигурационного файла модуля."""
    module_name = __name__.split(".")[-2]
    config_path = os.path.join(base_dir, "modules", module_name, "config.json")
    try:
        if not os.path.exists(config_path):
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            default_config = {key: info["default"] for key, info in GLOBAL_PARAMETERS.items()}
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
            logger.info(f"Создан новый config.json: {config_path}")
    except Exception as e:
        logger.error(f"Ошибка при инициализации конфигурации: {e}")
        raise

def load_config(base_dir):
    """Загрузка конфигурации модуля."""
    module_name = __name__.split(".")[-2]
    config_path = os.path.join(base_dir, "modules", module_name, "config.json")
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {key: info["default"] for key, info in GLOBAL_PARAMETERS.items()}
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}")
        return {key: info["default"] for key, info in GLOBAL_PARAMETERS.items()}

async def get_user_config(db, user_id):
    """Получение пользовательских настроек из базы данных."""
    if db is None:
        logger.error("База данных не инициализирована!")
        return {}
    module_name = __name__.split(".")[-2]
    table_name = f"{module_name}_config"
    try:
        async with db.execute(f"SELECT example_user_param FROM {table_name} WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"example_user_param": row[0]}
        return {}
    except Exception as e:
        logger.error(f"Ошибка при получении настроек пользователя {user_id}: {e}")
        return {}

async def set_user_config(db, user_id, config):
    """Сохранение пользовательских настроек в базе данных."""
    if db is None:
        logger.error("База данных не инициализирована!")
        return
    module_name = __name__.split(".")[-2]
    table_name = f"{module_name}_config"
    try:
        if config is None:
            await db.execute(f"DELETE FROM {table_name} WHERE user_id = ?", (user_id,))
        else:
            param = config.get("example_user_param", USER_PARAMETERS["example_user_param"]["default"])
            await db.execute(
                f"INSERT OR REPLACE INTO {table_name} (user_id, example_user_param) VALUES (?, ?)",
                (user_id, param)
            )
        await db.commit()
        logger.info(f"Настройки пользователя {user_id} обновлены: {config}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек пользователя {user_id}: {e}")
        raise

async def get_settings_menu(user_id, is_enabled, admin_ids, kernel_data):
    """Формирование меню настроек модуля."""
    module_name = __name__.split(".")[-2]
    text = (f"📋 **{DISPLAY_NAME}** ({'🟢 Вкл' if is_enabled else '🔴 Выкл'})\n"
            f"📝 **Описание:** {DESCRIPTION}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ **Текущие настройки:**\n")
    
    keyboard = []
    
    # Глобальные параметры (для админов)
    if user_id in admin_ids:
        global_config = load_config(kernel_data["base_dir"])
        for param, info in GLOBAL_PARAMETERS.items():
            value = global_config.get(param, info["default"])
            text += f"🔧 {info['description']}: **{value}**\n"
        text += "\n"
        for param in GLOBAL_PARAMETERS:
            keyboard.append([types.InlineKeyboardButton(
                text=f"🔧 Изменить {param}",
                callback_data=f"set_global_{module_name}_{param}"
            )])
        keyboard.append([types.InlineKeyboardButton(
            text=f"{'🔴 Выключить' if is_enabled else '🟢 Включить'}",
            callback_data=f"toggle_{module_name}"
        )])
        keyboard.append([types.InlineKeyboardButton(
            text="🗑️ Удалить модуль",
            callback_data=f"delete_module_{module_name}"
        )])

    # Пользовательские параметры
    user_config = await get_user_config(kernel_data["db"], user_id)
    for param, info in USER_PARAMETERS.items():
        value = user_config.get(param, info["default"])
        text += f"👤 {info['description']}: **{value}**\n"
    for param in USER_PARAMETERS:
        keyboard.append([types.InlineKeyboardButton(
            text=f"👤 Изменить {param}",
            callback_data=f"set_user_{module_name}_{param}"
        )])
    if user_config:
        keyboard.append([types.InlineKeyboardButton(
            text="🗑️ Удалить мои настройки",
            callback_data=f"delete_config_{module_name}"
        )])
    
    keyboard.append([types.InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="list_modules"
    )])
    
    return text, keyboard

@router.message(Command("command_name"))
async def command_handler(message: types.Message, state: FSMContext):
    """Обработка основной команды модуля."""
    if _kernel_data is None:
        await message.answer("❌ Ошибка: модуль не инициализирован корректно!")
        return
    
    db = _kernel_data.get("db")
    if db is None:
        await message.answer("❌ Ошибка: база данных не инициализирована!")
        return
    
    args = message.text.replace("/command_name", "").strip()
    if args:
        await message.answer(f"Вы ввели: {args}")
    else:
        await message.answer("Пожалуйста, введите данные:")
        await state.set_state(ModuleStates.waiting_for_input)

@router.message(ModuleStates.waiting_for_input)
async def process_input(message: types.Message, state: FSMContext):
    """Обработка ввода пользователя."""
    input_data = message.text.strip()
    if not input_data:
        await message.answer("Пожалуйста, введите корректные данные:")
        return
    
    await message.answer(f"Получено: {input_data}")
    await state.clear()

def get_commands():
    """Список команд модуля."""
    return [
        {"command": types.BotCommand(command="/command_name", description="Описание команды"), "access": "all"}
    ]

async def on_startup(kernel_data):
    """Действия при запуске модуля."""
    logger.info(f"Модуль {DISPLAY_NAME} запущен")

async def on_shutdown(kernel_data):
    """Действия при завершении работы модуля."""
    logger.info(f"Модуль {DISPLAY_NAME} завершён")
