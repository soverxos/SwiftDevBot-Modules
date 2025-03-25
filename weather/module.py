import os
import json
import logging
import asyncio
import aiohttp
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Настройка логирования
logger = logging.getLogger(__name__)

# Инициализация роутера для обработки сообщений и callback-запросов
router = Router()

# Глобальная переменная для хранения kernel_data
_kernel_data = None

# Определение состояний для FSM (Finite State Machine)
class WeatherStates(StatesGroup):
    waiting_for_city = State()

# Метаданные модуля
DISPLAY_NAME = "Погода/Weather 🌦️"
DESCRIPTION = "Модуль для получения текущей погоды в указанном городе через OpenWeatherMap."
GLOBAL_PARAMETERS = {
    "api_key": {
        "description": "API ключ для OpenWeatherMap (получите на openweathermap.org)",
        "required": True
    }
}
USER_PARAMETERS = {
    "city": {
        "description": "Город для получения погоды (например, Харьков)",
        "required": False
    },
    "locality": {
        "description": "Населённый пункт (например, посёлок Солнечный)",
        "required": False
    }
}

def setup(kernel_data):
    """Инициализация модуля при загрузке."""
    global _kernel_data
    _kernel_data = kernel_data
    db = kernel_data.get("db")
    if db is None:
        logger.error("База данных не инициализирована в kernel_data['db'] при настройке weather_module!")
        raise ValueError("База данных не инициализирована!")
    
    # Асинхронно инициализируем базу данных
    asyncio.create_task(init_db(db))
    
    # Инициализируем конфигурацию модуля
    init_config(kernel_data["base_dir"])
    
    logger.info("Модуль weather_module успешно загружен и настроен")

async def init_db(db):
    """Инициализация таблицы в базе данных для хранения настроек пользователей."""
    try:
        # Проверяем, существует ли таблица weather_config
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='weather_config'") as cursor:
            if not await cursor.fetchone():
                await db.execute("""
                    CREATE TABLE weather_config (
                        user_id INTEGER PRIMARY KEY,
                        city TEXT,
                        locality TEXT
                    )
                """)
                await db.commit()
                logger.info("Таблица weather_config создана с полями user_id, city, locality")
            else:
                # Проверяем наличие столбца locality и добавляем его, если отсутствует
                async with db.execute("PRAGMA table_info(weather_config)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]
                    if "locality" not in columns:
                        await db.execute("ALTER TABLE weather_config ADD COLUMN locality TEXT")
                        await db.commit()
                        logger.info("Добавлен столбец locality в таблицу weather_config")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных для weather_module: {e}")
        raise
    
    logger.info("Таблица weather_config успешно инициализирована")

def init_config(base_dir):
    """Инициализация конфигурационного файла модуля."""
    config_path = os.path.join(base_dir, "modules", "weather", "config.json")
    try:
        if not os.path.exists(config_path):
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=4, ensure_ascii=False)
            logger.info(f"Создан новый config.json для weather_module: {config_path}")
        else:
            logger.info(f"Конфигурация weather_module уже существует: {config_path}")
    except Exception as e:
        logger.error(f"Ошибка при инициализации конфигурации weather_module: {e}")
        raise

def load_config(base_dir):
    """Загрузка конфигурации модуля из файла."""
    config_path = os.path.join(base_dir, "modules", "weather", "config.json")
    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации weather_module: {e}")
        return {}

async def get_user_config(db, user_id):
    """Получение пользовательских настроек из базы данных."""
    if db is None:
        logger.error("База данных не инициализирована при вызове get_user_config!")
        return {}
    
    try:
        async with db.execute("SELECT city, locality FROM weather_config WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"city": row[0], "locality": row[1]}
        return {}
    except Exception as e:
        logger.error(f"Ошибка при получении настроек пользователя {user_id} для weather_module: {e}")
        return {}

async def set_user_config(db, user_id, config):
    """Сохранение пользовательских настроек в базе данных."""
    if db is None:
        logger.error("База данных не инициализирована при вызове set_user_config!")
        return
    
    try:
        if config is None:
            # Удаляем настройки пользователя
            await db.execute("DELETE FROM weather_config WHERE user_id = ?", (user_id,))
        else:
            city = config.get("city")
            locality = config.get("locality")
            await db.execute(
                "INSERT OR REPLACE INTO weather_config (user_id, city, locality) VALUES (?, ?, ?)",
                (user_id, city, locality)
            )
        await db.commit()
        logger.info(f"Настройки пользователя {user_id} для weather_module обновлены: {config}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении настроек пользователя {user_id} для weather_module: {e}")
        raise

async def get_weather(city, api_key):
    """Получение данных о погоде через API OpenWeatherMap."""
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric&lang=ru"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return f"❌ Ошибка: не удалось получить данные о погоде для {city} (код {response.status})"
                data = await response.json()
                temp = data["main"]["temp"]
                feels_like = data["main"]["feels_like"]
                description = data["weather"][0]["description"]
                humidity = data["main"]["humidity"]
                wind_speed = data["wind"]["speed"]
                return (f"🌦️ **Погода в {city}:**\n"
                        f"🌡️ Температура: **{temp}°C**\n"
                        f"🥵 Ощущается как: **{feels_like}°C**\n"
                        f"📜 Описание: **{description}**\n"
                        f"💧 Влажность: **{humidity}%**\n"
                        f"💨 Скорость ветра: **{wind_speed} м/с**")
    except aiohttp.ClientError as e:
        return f"❌ Ошибка при получении погоды для {city}: проблемы с сетью ({e})"
    except KeyError as e:
        return f"❌ Ошибка при обработке данных о погоде для {city}: некорректный ответ от API ({e})"
    except Exception as e:
        return f"❌ Ошибка при получении погоды для {city}: {e}"

async def get_settings_menu(user_id, is_enabled, admin_ids, kernel_data):
    """Формирование меню настроек модуля."""
    text = (f"📋 **{DISPLAY_NAME}** ({'🟢 Вкл' if is_enabled else '🔴 Выкл'})\n"
            f"📝 **Описание:** {DESCRIPTION}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ **Текущие настройки:**\n")
    
    keyboard = []
    
    # Отображаем глобальные параметры для администраторов
    if user_id in admin_ids:
        global_config = load_config(kernel_data["base_dir"])
        for param, info in GLOBAL_PARAMETERS.items():
            value = global_config.get(param, "Не настроен")
            text += f"🔧 {info['description']}: **{value}**\n"
        text += "\n"
    
    # Отображаем пользовательские параметры
    user_config = await get_user_config(kernel_data["db"], user_id)
    for param, info in USER_PARAMETERS.items():
        value = user_config.get(param) if user_config else "Не настроен"
        text += f"👤 {info['description']}: **{value}**\n"
    
    text += f"━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += "🛠 **Действия:**\n"
    
    # Кнопка включения/выключения модуля (только для админов)
    if user_id in admin_ids:
        keyboard.append([types.InlineKeyboardButton(
            text=f"{'🔴 Выключить' if is_enabled else '🟢 Включить'}",
            callback_data="toggle_weather"
        )])
    
    # Кнопки для изменения глобальных параметров (только для админов)
    if user_id in admin_ids:
        for param in GLOBAL_PARAMETERS:
            keyboard.append([types.InlineKeyboardButton(
                text=f"🔑 Изменить {param}",
                callback_data=f"set_global_weather_{param}"
            )])
    
    # Кнопки для изменения пользовательских параметров
    for param in USER_PARAMETERS:
        emoji = "🏙️" if param == "city" else "🌍"  # Разные эмодзи для city и locality
        keyboard.append([types.InlineKeyboardButton(
            text=f"{emoji} Изменить {param}",
            callback_data=f"set_user_weather_{param}"
        )])
    
    # Кнопка удаления пользовательских настроек
    if user_config:
        keyboard.append([types.InlineKeyboardButton(
            text="🗑️ Удалить мои настройки",
            callback_data="delete_config_weather"
        )])
    
    # Кнопка удаления модуля (только для админов)
    if user_id in admin_ids:
        keyboard.append([types.InlineKeyboardButton(
            text="🗑️ Удалить модуль",
            callback_data="delete_module_weather"
        )])
    
    # Кнопка возврата в список модулей
    keyboard.append([types.InlineKeyboardButton(
        text="⬅️ Назад",
        callback_data="list_modules"
    )])
    
    return text, keyboard  # Возвращаем только текст и список кнопок, без InlineKeyboardMarkup

@router.message(Command("weather"))
async def weather_command(message: types.Message, state: FSMContext):
    """Обработка команды /weather для получения погоды."""
    if _kernel_data is None:
        await message.answer("❌ Ошибка: модуль не инициализирован корректно!")
        return
    
    db = _kernel_data.get("db")
    if db is None:
        await message.answer("❌ Ошибка: база данных не инициализирована!")
        return

    # Проверяем, указан ли город в команде
    command_args = message.text.replace("/weather", "").strip()
    if command_args:
        city = command_args
    else:
        # Если город не указан, пытаемся взять его из настроек пользователя
        user_config = await get_user_config(db, message.from_user.id)
        city = user_config.get("city")
        locality = user_config.get("locality")
        if locality:
            city = f"{city}, {locality}" if city else locality
        if not city:
            await message.answer("🏙️ Пожалуйста, укажите город для получения погоды:")
            await state.set_state(WeatherStates.waiting_for_city)
            return
    
    # Загружаем API-ключ из конфигурации
    config = load_config(_kernel_data["base_dir"])
    api_key = config.get("api_key")
    if not api_key:
        await message.answer("❌ Ошибка: API-ключ для OpenWeatherMap не настроен. Обратитесь к администратору.")
        return
    
    # Получаем данные о погоде
    weather_info = await get_weather(city, api_key)
    await message.answer(weather_info, parse_mode="Markdown")
    logger.info(f"Погода для города {city} отправлена пользователю {message.from_user.id}")

@router.message(WeatherStates.waiting_for_city)
async def process_city(message: types.Message, state: FSMContext):
    """Обработка ввода города пользователем."""
    city = message.text.strip()
    if not city:
        await message.answer("🏙️ Пожалуйста, укажите корректный город:")
        return
    
    # Загружаем API-ключ из конфигурации
    config = load_config(_kernel_data["base_dir"])
    api_key = config.get("api_key")
    if not api_key:
        await message.answer("❌ Ошибка: API-ключ для OpenWeatherMap не настроен. Обратитесь к администратору.")
        await state.clear()
        return
    
    # Проверяем, есть ли уже сохранённый город
    db = _kernel_data.get("db")
    user_config = await get_user_config(db, message.from_user.id)
    was_city_empty = not user_config.get("city")  # Проверяем, был ли город пустым до этого
    
    # Сохраняем город в пользовательских настройках
    user_config["city"] = city
    await set_user_config(db, message.from_user.id, user_config)
    
    # Получаем данные о погоде
    weather_info = await get_weather(city, api_key)
    
    # Если это первый ввод города, добавляем уведомление
    if was_city_empty and not weather_info.startswith("❌"):
        weather_info += f"\n\n✅ Город \"{city}\" сохранён как город по умолчанию."
    
    await message.answer(weather_info, parse_mode="Markdown")
    logger.info(f"Погода для города {city} отправлена пользователю {message.from_user.id} после ввода")
    
    # Сбрасываем состояние
    await state.clear()

def get_commands():
    """Возвращает список команд модуля."""
    return [
        {"command": types.BotCommand(command="/weather", description="🌦️ Узнать погоду в городе"), "access": "all"}
    ]

async def on_startup(kernel_data):
    """Действия при запуске модуля."""
    logger.info("Модуль weather_module запущен")

async def on_shutdown(kernel_data):
    """Действия при завершении работы модуля."""
    logger.info("Модуль weather_module завершён")
