"""
Шаблон модуля для SwiftDevBot
Этот файл — основа для создания любого модуля. Он максимально гибкий и функциональный.
Следуй комментариям, чтобы понять, как всё работает, и адаптируй под свои нужды!

[ВАЖНО] Минимально необходимые компоненты для работы модуля:
1. Константы: MODULE_NAME, DISPLAY_NAME, VERSION
2. Функции: register_module(), install()

Все остальные компоненты опциональны и могут быть добавлены по необходимости.
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List
from aiogram import types, Dispatcher
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- Логирование ---
# [ОБЯЗАТЕЛЬНО] Каждый модуль должен использовать свой логгер
logger = logging.getLogger(f"modules.{__name__}")

# --- Основные константы модуля ---
# [ОБЯЗАТЕЛЬНО] Эти константы необходимы для корректной работы модуля
MODULE_NAME = "template_module"  # Должно совпадать с именем папки модуля
DISPLAY_NAME = "Шаблонный Модуль"
VERSION = "1.0.0"
# [ОПЦИОНАЛЬНО] Эти константы используются для улучшения пользовательского опыта
MODULE_ICON = "📟"  # Иконка модуля для красоты сообщений
kernel_data = None  # Здесь будут данные ядра бота (бот, конфиг и т.д.)

# --- Локализация (многоязычность) ---
# [ОПЦИОНАЛЬНО] Поддержка разных языков. Добавь свои сообщения сюда!
LANGUAGES = {
    "ru": {
        "welcome": "Добро пожаловать в {name} v{version}!",
        "info": "ℹ️ Это {name} — пример модуля.",
        "action": "⚙️ {name} выполняет действие...",
        "settings": "🔧 Настройки {name}",
        "disabled": "⛔ {name} отключён.",
        "no_access": "⛔ У вас нет доступа к {name}."
    },
    "en": {
        "welcome": "Welcome to {name} v{version}!",
        "info": "ℹ️ This is {name} — a sample module.",
        "action": "⚙️ {name} is performing an action...",
        "settings": "🔧 {name} settings",
        "disabled": "⛔ {name} is disabled.",
        "no_access": "⛔ You don't have access to {name}."
    }
}

# --- Кэш для ускорения работы ---
# [ОПЦИОНАЛЬНО] Хранит данные, чтобы не запрашивать их каждый раз
CACHE = {}

# --- Состояния FSM ---
# [ОПЦИОНАЛЬНО] Используется для отслеживания, в каком "режиме" находится пользователь
class ModuleStates(StatesGroup):
    main = State()      # Главное меню
    settings = State()  # Настройки модуля

# --- Утилитарные функции ---
# [ОПЦИОНАЛЬНО] Вспомогательные функции для удобства работы с модулем
def get_text(key: str, lang: str = "ru") -> str:
    """Получает текст на нужном языке с подстановкой имени и версии."""
    return LANGUAGES.get(lang, LANGUAGES["ru"])[key].format(name=DISPLAY_NAME, version=VERSION)

def get_main_menu_kb() -> InlineKeyboardMarkup:
    """Создаёт основную клавиатуру модуля."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"ℹ️ О {DISPLAY_NAME}", callback_data="info")],
        [InlineKeyboardButton(text="⚙️ Действие", callback_data="action")],
        [InlineKeyboardButton(text="🔧 Настройки", callback_data="settings")]
    ])

def get_settings_kb() -> InlineKeyboardMarkup:
    """Создаёт клавиатуру для настроек."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

# [РЕКОМЕНДУЕТСЯ] Проверка статуса модуля для предотвращения использования отключенного модуля
def is_module_enabled() -> bool:
    """Проверяет, включён ли модуль в конфигурации."""
    return kernel_data["config"]["modules"].get(MODULE_NAME, False)

def check_permissions(user_id: int, admin_only: bool = False) -> bool:
    """Проверяет, имеет ли пользователь доступ."""
    if admin_only:
        return user_id in kernel_data.get("admin_ids", [])
    return True  # Если admin_only=False, доступ есть у всех

async def update_stats(action: str) -> None:
    """Обновляет статистику использования модуля в базе данных."""
    db = kernel_data.get("db")
    if db:
        await db.execute(
            "INSERT INTO module_stats (module, action, uses) VALUES (?, ?, 1) "
            "ON CONFLICT(module, action) DO UPDATE SET uses=uses+1",
            (MODULE_NAME, action)
        )
        await db.commit()

# --- Обработчики команд ---
# [РЕКОМЕНДУЕТСЯ] Основной обработчик команды модуля
async def module_command(message: types.Message, state: FSMContext, kernel_data: Dict[str, Any]) -> None:
    """
    Основная команда модуля. Вызывается, когда пользователь вводит /template_module.
    Пример: /template_module
    
    [ВАЖНО] Параметр state должен всегда присутствовать - не создавайте FSMContext вручную!
    """
    if not is_module_enabled():
        logger.info(f"⛔ Модуль {DISPLAY_NAME} ({MODULE_NAME}) отключён")
        await message.answer(get_text("disabled"))
        return
    
    if not check_permissions(message.from_user.id, admin_only=False):
        logger.info(f"⛔ Доступ к /{MODULE_NAME} запрещён для {message.from_user.id}")
        await message.answer(get_text("no_access"))
        return
    
    logger.info(f"📌 Запуск команды /{MODULE_NAME} для {message.from_user.id}")
    await update_stats("command_used")
    
    # Отправляем приветственное сообщение с клавиатурой
    await message.answer(
        f"{MODULE_ICON} {get_text('welcome')}\nВыберите действие:",
        reply_markup=get_main_menu_kb()
    )
    
    # [ВАЖНО] Используем переданный параметр state, а не создаем новый FSMContext
    await state.set_state(ModuleStates.main)

# --- Обработчики колбэков ---
# [ОПЦИОНАЛЬНО] Обработчик нажатий на инлайн-кнопки
async def process_callback(callback: types.CallbackQuery, state: FSMContext, kernel_data: Dict[str, Any]) -> None:
    """
    Обрабатывает нажатия на inline-кнопки.
    Пример: Пользователь нажимает "О модуле" -> вызывается этот код.
    
    [ВАЖНО] Параметр state должен присутствовать для работы с состояниями
    """
    if not is_module_enabled():
        logger.info(f"⛔ Модуль {DISPLAY_NAME} ({MODULE_NAME}) отключён")
        await callback.answer(get_text("disabled"), show_alert=True)
        return
    
    if not check_permissions(callback.from_user.id, admin_only=False):
        logger.info(f"⛔ Доступ к колбэку {callback.data} запрещён для {callback.from_user.id}")
        await callback.answer(get_text("no_access"), show_alert=True)
        return
    
    data = callback.data
    logger.info(f"🔍 Обработка колбэка: {data} от {callback.from_user.id}")
    await update_stats(f"callback_{data}")
    
    if data == "info":
        await callback.message.edit_text(
            f"{MODULE_ICON} {get_text('info')}",
            reply_markup=get_main_menu_kb()
        )
    elif data == "action":
        await callback.message.edit_text(
            f"{MODULE_ICON} {get_text('action')}",
            reply_markup=get_main_menu_kb()
        )
    elif data == "settings":
        await callback.message.edit_text(
            f"{MODULE_ICON} {get_text('settings')}\n(В разработке)",
            reply_markup=get_settings_kb()
        )
        await state.set_state(ModuleStates.settings)
    elif data == "back_to_main":
        await callback.message.edit_text(
            f"{MODULE_ICON} {get_text('welcome')}\nВыберите действие:",
            reply_markup=get_main_menu_kb()
        )
        await state.set_state(ModuleStates.main)
    else:
        await callback.answer(f"❓ Неизвестная команда: {data}", show_alert=True)
    
    await callback.answer()

# --- Обработка событий ---
# [ОПЦИОНАЛЬНО] Обработчик всех сообщений (не команд)
async def on_message(message: types.Message, kernel_data: Dict[str, Any]) -> None:
    """
    Реагирует на все сообщения (не команды). Полезно для модулей вроде фильтров.
    Пример: Пользователь пишет "привет" -> модуль отвечает "Привет обратно!"
    
    [ВАЖНО] Используйте этот обработчик осторожно, так как он может перехватывать
    все сообщения и мешать работе других модулей!
    """
    if not is_module_enabled():
        return
    logger.info(f"📩 {DISPLAY_NAME} получил сообщение от {message.from_user.id}: {message.text}")
    # Пример: эхо для всех сообщений
    # await message.reply(f"{MODULE_ICON} Ты сказал: {message.text}")

# --- Интеграция с ядром ---
# [ОБЯЗАТЕЛЬНО] Функция регистрации модуля - НЕОБХОДИМА для работы модуля
def register_module(dp: Dispatcher, data: Dict[str, Any]) -> None:
    """
    Регистрирует модуль в системе бота. Эта функция вызывается ядром при загрузке модуля.
    
    [ВАЖНО] Эта функция ОБЯЗАТЕЛЬНА для всех модулей
    """
    global kernel_data
    kernel_data = data
    
    # [ОБЯЗАТЕЛЬНО] Регистрация команды для запуска модуля
    dp.message.register(module_command, Command(commands=[MODULE_NAME]))
    
    # [РЕКОМЕНДУЕТСЯ] Используйте фильтры для колбэков, чтобы не перехватывать чужие
    from aiogram.filters import Text
    module_callbacks = ["info", "action", "settings", "back_to_main"]
    dp.callback_query.register(process_callback, Text(text=module_callbacks))
    
    # [ОПЦИОНАЛЬНО] Регистрация обработчика всех сообщений
    # [ВАЖНО] Используйте только если действительно нужно обрабатывать все сообщения
    from aiogram.filters import ChatTypeFilter
    dp.message.register(on_message, ~Command(), ChatTypeFilter(types.ChatType.PRIVATE))
    
    # [РЕКОМЕНДУЕТСЯ] Регистрация команды в меню бота
    command_registry = kernel_data["command_registry"]
    command_registry.register_command(
        command=MODULE_NAME,
        description=f"Запустить {DISPLAY_NAME}",
        icon=MODULE_ICON,
        category="Utility",
        admin=False
    )
    logger.info(f"✅ Модуль {DISPLAY_NAME} ({MODULE_NAME}) зарегистрирован")

# --- Установка модуля ---
# [ОБЯЗАТЕЛЬНО] Функция установки модуля - НЕОБХОДИМА для работы модуля
async def install(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Выполняется при установке модуля.
    Может возвращать настройки, которые бот сохранит в config.json.
    
    [ВАЖНО] Эта функция ОБЯЗАТЕЛЬНА для всех модулей
    """
    global kernel_data
    kernel_data = data
    logger.info(f"✅ Модуль {DISPLAY_NAME} ({MODULE_NAME}) установлен")
    
    # [ОПЦИОНАЛЬНО] Возврат настроек модуля
    return {
        "welcome_message": {
            "type": "string",
            "default": f"Добро пожаловать в {DISPLAY_NAME}!",
            "description": "Сообщение при запуске модуля",
            "required": False
        },
        "mode": {
            "type": "choice",
            "options": ["simple", "advanced"],
            "default": "simple",
            "description": "Режим работы модуля"
        }
    }

# --- Завершение работы ---
# [ОПЦИОНАЛЬНО] Функция вызывается при выключении бота
async def on_shutdown(data: Dict[str, Any]) -> None:
    """
    Выполняется при выключении бота.
    Полезно для сохранения данных или очистки.
    
    [ОПЦИОНАЛЬНО] Этот метод не обязателен, но рекомендуется для освобождения ресурсов
    """
    logger.info(f"🛑 Модуль {DISPLAY_NAME} ({MODULE_NAME}) завершает работу")
    CACHE.clear()  # Очищаем кэш

# --- Фоновая задача ---
# [ОПЦИОНАЛЬНО] Фоновая задача, работающая постоянно
async def background_task() -> None:
    """
    Фоновая задача, которая работает постоянно.
    Пример: Отправка уведомлений каждые 60 секунд.
    
    [ВАЖНО] Всегда используйте asyncio.sleep вместо time.sleep в асинхронных функциях!
    """
    while True:
        logger.info(f"🕒 {DISPLAY_NAME} выполняет фоновую задачу")
        # Пример: Отправка сообщения админам
        # for admin_id in kernel_data["admin_ids"]:
        #     await kernel_data["bot"].send_message(admin_id, f"{MODULE_ICON} Я работаю!")
        await asyncio.sleep(60)

# [ОПЦИОНАЛЬНО] Регистрация фоновых задач
def register_background_tasks(data: Dict[str, Any]) -> None:
    """
    Регистрирует фоновые задачи в ядре.
    
    [ОПЦИОНАЛЬНО] Используйте только если модулю нужны фоновые задачи
    """
    data["background_tasks"][MODULE_NAME] = [background_task]
    logger.info(f"🕒 Фоновая задача для {DISPLAY_NAME} зарегистрирована")

# --- Пример использования кэша ---
# [ОПЦИОНАЛЬНО] Вспомогательная функция для работы с кэшем
async def get_cached_data(key: str, fetch_func: callable) -> Any:
    """
    Получает данные из кэша или запрашивает их.
    Пример: result = await get_cached_data("user_count", get_user_count)
    
    [ОПЦИОНАЛЬНО] Вспомогательная функция для оптимизации запросов
    """
    if key not in CACHE:
        CACHE[key] = await fetch_func()
    return CACHE[key]