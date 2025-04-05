"""
Модуль погоды для SwiftDevBot
Предоставляет прогноз погоды для любого города мира с множеством настроек и детальной информацией.
Поддерживает сохранение избранных городов, настройку единиц измерения, уведомления и многое другое.

[ВАЖНО] Для работы необходим API-ключ OpenWeatherMap (получить бесплатно на https://openweathermap.org)
"""
import os
import json
import logging
import asyncio
import aiohttp
import time
from datetime import datetime, timedelta
from io import BytesIO
import matplotlib.pyplot as plt
from typing import Optional, Dict, Any, List, Tuple
from aiogram import types, Dispatcher
from aiogram.filters import Command, Text
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- Логирование ---
# [ОБЯЗАТЕЛЬНО] Каждый модуль должен использовать свой логгер
logger = logging.getLogger(f"modules.weather")

# --- Основные константы модуля ---
# [ОБЯЗАТЕЛЬНО] Эти константы необходимы для корректной работы модуля
MODULE_NAME = "weather"
DISPLAY_NAME = "Прогноз погоды"
VERSION = "1.0.0"
# [ОПЦИОНАЛЬНО] Эти константы используются для улучшения пользовательского опыта
MODULE_ICON = "🌤️"
kernel_data = None

# --- API константы ---
BASE_URL = "https://api.openweathermap.org/data/2.5"
DEFAULT_API_KEY = ""  # Получить на https://openweathermap.org
GEOCODING_URL = "http://api.openweathermap.org/geo/1.0/direct"
ONECALL_URL = "https://api.openweathermap.org/data/3.0/onecall"
ICON_URL = "http://openweathermap.org/img/wn/{icon}@2x.png"

# --- Константы путей ---
# [РЕКОМЕНДУЕТСЯ] Стандартные пути для файлов модуля
MODULE_DATA_DIR = None  # Будет установлено в install()
CONFIG_FILENAME = "config.json"
PLOTS_DIR = None  # Директория для сохранения графиков

# --- Настройки по умолчанию ---
# [РЕКОМЕНДУЕТСЯ] Настройки модуля с значениями по умолчанию
DEFAULT_SETTINGS = {
    "api_key": {
        "type": "string",
        "default": DEFAULT_API_KEY,
        "description": "API ключ OpenWeatherMap",
        "required": True
    },
    "units": {
        "type": "choice",
        "options": ["metric", "imperial"],
        "default": "metric",
        "description": "Единицы измерения (metric - °C, км/ч; imperial - °F, миль/ч)"
    },
    "time_format": {
        "type": "choice", 
        "options": ["12h", "24h"], 
        "default": "24h",
        "description": "Формат времени (12/24 часа)"
    },
    "language": {
        "type": "choice",
        "options": ["ru", "en", "de", "fr", "es"],
        "default": "ru",
        "description": "Язык прогноза погоды"
    },
    "forecast_days": {
        "type": "int",
        "default": 5,
        "min": 1,
        "max": 7,
        "description": "Количество дней прогноза"
    },
    "notifications_enabled": {
        "type": "bool",
        "default": False,
        "description": "Включить уведомления о погоде"
    },
    "notification_time": {
        "type": "string",
        "default": "08:00",
        "description": "Время ежедневного уведомления (формат HH:MM)"
    }
}

# --- Получение настроек ---
def get_module_settings():
    """Получает настройки модуля из конфигурации или использует значения по умолчанию."""
    if not kernel_data:
        return {k: v.get("default") if isinstance(v, dict) else v for k, v in DEFAULT_SETTINGS.items()}
    
    # Получаем настройки из конфиг-файла
    settings = kernel_data.get("config", {}).get("modules_settings", {}).get(MODULE_NAME, {})
    
    # Объединяем настройки по умолчанию с настройками из конфигурации
    result = {}
    for key, value in DEFAULT_SETTINGS.items():
        if isinstance(value, dict) and "default" in value:
            # Если это полное описание настройки
            if key in settings:
                result[key] = settings[key]
            else:
                result[key] = value["default"]
        else:
            # Если это просто значение
            result[key] = settings.get(key, value)
    
    return result

# --- Работа с локальным конфигом ---
def get_local_config_path():
    if not MODULE_DATA_DIR:
        return None
    return os.path.join(MODULE_DATA_DIR, CONFIG_FILENAME)

def load_local_config():
    config_path = get_local_config_path()
    if not config_path or not os.path.exists(config_path):
        return {}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки локального конфига: {e}")
        return {}

def save_local_config(config_data):
    if not MODULE_DATA_DIR:
        logger.error("❌ MODULE_DATA_DIR не установлен, невозможно сохранить конфиг")
        return False
    
    os.makedirs(MODULE_DATA_DIR, exist_ok=True)
    config_path = get_local_config_path()
    
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения локального конфига: {e}")
        return False

# --- Пользовательские настройки ---
async def get_user_city(user_id: int) -> str:
    """Получает город по умолчанию для пользователя"""
    config = load_local_config()
    try:
        return config.get("user_preferences", {}).get(str(user_id), {}).get("default_city", "Москва")
    except Exception:
        return "Москва"

async def set_user_city(user_id: int, city: str) -> bool:
    """Устанавливает город по умолчанию для пользователя"""
    config = load_local_config()
    
    if "user_preferences" not in config:
        config["user_preferences"] = {}
    
    if str(user_id) not in config["user_preferences"]:
        config["user_preferences"][str(user_id)] = {}
    
    config["user_preferences"][str(user_id)]["default_city"] = city
    config["user_preferences"][str(user_id)]["updated_at"] = str(datetime.now())
    
    return save_local_config(config)

async def get_favorite_cities(user_id: int) -> List[str]:
    """Получает список избранных городов пользователя"""
    config = load_local_config()
    try:
        return config.get("user_preferences", {}).get(str(user_id), {}).get("favorite_cities", [])
    except Exception:
        return []

async def add_favorite_city(user_id: int, city: str) -> bool:
    """Добавляет город в избранное"""
    config = load_local_config()
    
    if "user_preferences" not in config:
        config["user_preferences"] = {}
    
    if str(user_id) not in config["user_preferences"]:
        config["user_preferences"][str(user_id)] = {}
    
    if "favorite_cities" not in config["user_preferences"][str(user_id)]:
        config["user_preferences"][str(user_id)]["favorite_cities"] = []
    
    # Проверяем, есть ли уже такой город
    favorite_cities = config["user_preferences"][str(user_id)]["favorite_cities"]
    if city not in favorite_cities:
        favorite_cities.append(city)
    
    return save_local_config(config)

async def remove_favorite_city(user_id: int, city: str) -> bool:
    """Удаляет город из избранного"""
    config = load_local_config()
    try:
        if city in config["user_preferences"][str(user_id)]["favorite_cities"]:
            config["user_preferences"][str(user_id)]["favorite_cities"].remove(city)
            return save_local_config(config)
    except Exception:
        pass
    return False

# --- Кэширование погодных данных ---
CACHE = {}
CACHE_LIFETIME = 1800  # 30 минут в секундах

def get_cache_key(city: str, forecast_type: str = "current") -> str:
    """Создает ключ для кэша"""
    return f"{city.lower()}:{forecast_type}"

def get_cached_weather(city: str, forecast_type: str = "current") -> Optional[Dict]:
    """Получает погоду из кэша, если она актуальна"""
    key = get_cache_key(city, forecast_type)
    if key in CACHE:
        cached_data = CACHE[key]
        # Проверяем, не устарел ли кэш
        if time.time() - cached_data["timestamp"] < CACHE_LIFETIME:
            return cached_data["data"]
    return None

def set_cached_weather(city: str, data: Dict, forecast_type: str = "current") -> None:
    """Сохраняет погоду в кэш"""
    key = get_cache_key(city, forecast_type)
    CACHE[key] = {
        "data": data,
        "timestamp": time.time()
    }

# --- Состояния FSM ---
class WeatherStates(StatesGroup):
    main = State()           # Главное меню
    settings = State()       # Настройки 
    city_input = State()     # Ввод города
    favorites = State()      # Избранные города
    detailed = State()       # Подробный прогноз
    edit_setting = State()   # Редактирование настройки

# --- Локализация ---
LANGUAGES = {
    "ru": {
        "welcome": "Добро пожаловать в {name} v{version}!",
        "city_prompt": "🏙️ Введите название города для прогноза погоды",
        "loading": "⏳ Загружаю прогноз погоды для {city}...",
        "error": "❌ Ошибка получения прогноза: {error}",
        "current_weather": "🌤️ <b>Текущая погода в {city}</b>",
        "forecast": "📅 <b>Прогноз погоды на {days} дней для {city}</b>",
        "not_found": "🔍 Город {city} не найден. Попробуйте другой город.",
        "favorites_empty": "🔖 У вас пока нет избранных городов",
        "favorites_title": "🔖 <b>Избранные города</b>",
        "city_added": "✅ Город {city} добавлен в избранное",
        "city_removed": "❌ Город {city} удален из избранного",
        "city_default": "✅ Город {city} установлен по умолчанию",
        "settings_title": "⚙️ <b>Настройки прогноза погоды</b>",
        "disabled": "⛔ Модуль {name} отключён.",
        "no_access": "⛔ У вас нет доступа к {name}."
    },
    "en": {
        "welcome": "Welcome to {name} v{version}!",
        "city_prompt": "🏙️ Enter city name for weather forecast",
        "loading": "⏳ Loading weather forecast for {city}...",
        "error": "❌ Forecast error: {error}",
        "current_weather": "🌤️ <b>Current weather in {city}</b>",
        "forecast": "📅 <b>{days}-day forecast for {city}</b>",
        "not_found": "🔍 City {city} not found. Try another city.",
        "favorites_empty": "🔖 You don't have favorite cities yet",
        "favorites_title": "🔖 <b>Favorite Cities</b>",
        "city_added": "✅ {city} added to favorites",
        "city_removed": "❌ {city} removed from favorites",
        "city_default": "✅ {city} set as default city",
        "settings_title": "⚙️ <b>Weather Forecast Settings</b>",
        "disabled": "⛔ {name} module is disabled.",
        "no_access": "⛔ You don't have access to {name}."
    }
}

# --- Клавиатуры ---
def get_text(key: str, lang: str = "ru", **kwargs) -> str:
    """Получает текст на нужном языке с подстановкой параметров"""
    text = LANGUAGES.get(lang, LANGUAGES["ru"]).get(key, key).format(name=DISPLAY_NAME, version=VERSION, **kwargs)
    return text

def get_main_menu_kb() -> InlineKeyboardMarkup:
    """Создаёт основную клавиатуру модуля"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти город", callback_data="search_city")],
        [InlineKeyboardButton(text="🔖 Избранные города", callback_data="favorites")],
        [InlineKeyboardButton(text="📈 Подробный прогноз", callback_data="detailed_forecast")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")]
    ])

def get_forecast_kb(city: str, is_favorite: bool = False) -> InlineKeyboardMarkup:
    """Создает клавиатуру для прогноза"""
    favorite_btn = InlineKeyboardButton(
        text="❌ Удалить из избранного" if is_favorite else "⭐ Добавить в избранное", 
        callback_data=f"remove_favorite:{city}" if is_favorite else f"add_favorite:{city}"
    )
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [favorite_btn],
        [InlineKeyboardButton(text="📌 Сделать городом по умолчанию", callback_data=f"set_default:{city}")],
        [InlineKeyboardButton(text="📅 Прогноз на 5 дней", callback_data=f"forecast:{city}")],
        [InlineKeyboardButton(text="📊 График температуры", callback_data=f"temp_chart:{city}")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ])

def get_favorites_kb(cities: List[str]) -> InlineKeyboardMarkup:
    """Создает клавиатуру с избранными городами"""
    keyboard = []
    for city in cities:
        keyboard.append([InlineKeyboardButton(text=f"🏙️ {city}", callback_data=f"get_weather:{city}")])
    
    keyboard.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_settings_kb() -> InlineKeyboardMarkup:
    """Создаёт клавиатуру для настроек."""
    settings = get_module_settings()
    keyboard = []
    
    for key, value in settings.items():
        # Если это не api_key (для безопасности не показываем полный ключ)
        if key == "api_key":
            api_key = value
            display_value = f"{api_key[:5]}..." if api_key and len(api_key) > 5 else "Не настроен"
            keyboard.append([
                InlineKeyboardButton(text=f"🔑 API ключ: {display_value}", callback_data=f"edit_setting:{key}")
            ])
        else:
            display_value = value
            keyboard.append([
                InlineKeyboardButton(text=f"{key}: {display_value}", callback_data=f"edit_setting:{key}")
            ])
    
    keyboard.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# --- Вспомогательные функции ---
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

# --- API и погодные функции ---
async def fetch_weather_data(url: str, params: Dict) -> Dict:
    """Выполняет запрос к API погоды"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    logger.error(f"❌ Ошибка API: {response.status}, {await response.text()}")
                    return {"error": f"Ошибка API: {response.status}"}
                
                return await response.json()
        except Exception as e:
            logger.error(f"❌ Ошибка запроса: {e}")
            return {"error": f"Ошибка соединения: {e}"}

async def get_city_coordinates(city_name: str, api_key: str) -> Optional[Tuple[float, float, str]]:
    """Получает координаты города по его названию"""
    params = {
        "q": city_name,
        "limit": 1,
        "appid": api_key
    }
    
    data = await fetch_weather_data(GEOCODING_URL, params)
    
    if data and isinstance(data, list) and len(data) > 0:
        city = data[0]
        return city.get("lat"), city.get("lon"), city.get("name", city_name)
    
    return None

async def get_current_weather(city: str) -> Dict:
    """Получает текущую погоду для города"""
    # Проверяем кэш
    cached_data = get_cached_weather(city, "current")
    if cached_data:
        return cached_data
    
    settings = get_module_settings()
    api_key = settings["api_key"]
    units = settings["units"]
    lang = settings["language"]
    
    # Получаем координаты города
    coords = await get_city_coordinates(city, api_key)
    
    if not coords:
        return {"error": f"Город {city} не найден"}
    
    lat, lon, city_name = coords
    
    # Параметры запроса
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": units,
        "lang": lang,
        "exclude": "minutely,hourly"  # исключаем ненужные данные
    }
    
    data = await fetch_weather_data(ONECALL_URL, params)
    
    if "error" in data:
        return data
    
    # Добавляем название города в данные
    data["city_name"] = city_name
    
    # Кэшируем результат
    set_cached_weather(city, data, "current")
    
    return data

async def generate_temperature_chart(city: str) -> str:
    """Генерирует и сохраняет график температур на неделю"""
    weather_data = await get_current_weather(city)
    
    if "error" in weather_data:
        return None
    
    # Создаем график
    plt.figure(figsize=(10, 6))
    
    dates = []
    temps_day = []
    temps_night = []
    
    # Добавляем данные для каждого дня
    for day in weather_data.get("daily", [])[:7]:  # На неделю вперед
        dt = datetime.fromtimestamp(day.get("dt", 0))
        dates.append(dt.strftime("%d.%m"))
        temps_day.append(day.get("temp", {}).get("day", 0))
        temps_night.append(day.get("temp", {}).get("night", 0))
    
    # Строим график
    plt.plot(dates, temps_day, 'o-', color='orange', label='День')
    plt.plot(dates, temps_night, 'o-', color='blue', label='Ночь')
    
    # Настройка графика
    plt.title(f"Прогноз температуры для {city}")
    plt.xlabel("Дата")
    plt.ylabel("Температура")
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend()
    
    # Сохраняем во временный файл
    os.makedirs(PLOTS_DIR, exist_ok=True)
    timestamp = int(time.time())
    filename = os.path.join(PLOTS_DIR, f"temp_chart_{city}_{timestamp}.png")
    
    plt.savefig(filename)
    plt.close()
    
    return filename

def format_weather_message(weather_data: Dict, forecast_type: str = "current") -> str:
    """Форматирует сообщение о погоде"""
    if "error" in weather_data:
        return f"❌ Ошибка: {weather_data['error']}"
    
    settings = get_module_settings()
    units = settings["units"]
    lang = settings["language"]
    
    city_name = weather_data.get("city_name", "")
    current = weather_data.get("current", {})
    daily = weather_data.get("daily", [])
    
    # Определяем единицы измерения
    temp_unit = "°C" if units == "metric" else "°F"
    speed_unit = "м/с" if units == "metric" else "миль/ч"
    
    if forecast_type == "current":
        # Текущая погода
        temp = current.get("temp", 0)
        feels_like = current.get("feels_like", 0)
        humidity = current.get("humidity", 0)
        pressure = current.get("pressure", 0)
        wind_speed = current.get("wind_speed", 0)
        description = current.get("weather", [{}])[0].get("description", "")
        
        message = (
            f"🌤️ <b>Погода в {city_name}</b>\n"
            f"═════════════════════\n"
            f"🌡️ <b>Температура:</b> {temp}{temp_unit} (ощущается как {feels_like}{temp_unit})\n"
            f"☁️ <b>Состояние:</b> {description}\n"
            f"💧 <b>Влажность:</b> {humidity}%\n"
            f"🌬️ <b>Ветер:</b> {wind_speed} {speed_unit}\n"
            f"🔵 <b>Давление:</b> {pressure} гПа\n"
            f"🕒 <b>Обновлено:</b> {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"
        )
        
    elif forecast_type == "forecast":
        # Прогноз на несколько дней
        message = f"📅 <b>Прогноз погоды для {city_name}</b>\n═════════════════════\n"
        
        for day_data in daily[:5]:  # Ограничиваем 5 днями
            dt = datetime.fromtimestamp(day_data.get("dt", 0))
            day_name = dt.strftime("%A").capitalize()
            date_str = dt.strftime("%d.%m")
            
            day_temp = day_data.get("temp", {}).get("day", 0)
            night_temp = day_data.get("temp", {}).get("night", 0)
            description = day_data.get("weather", [{}])[0].get("description", "")
            
            message += (
                f"\n<b>{day_name} ({date_str}):</b>\n"
                f"  🌡️ Днём: {day_temp}{temp_unit}, Ночью: {night_temp}{temp_unit}\n"
                f"  ☁️ {description}\n"
            )
    
    return message

# --- Обработчики команд ---
async def weather_command(message: types.Message, state: FSMContext, kernel_data: Dict[str, Any]) -> None:
    """
    Основная команда модуля. Вызывается, когда пользователь вводит /weather.
    """
    if not is_module_enabled():
        logger.info(f"⛔ Модуль {DISPLAY_NAME} ({MODULE_NAME}) отключён")
        await message.answer(get_text("disabled"))
        return
    
    if not check_permissions(message.from_user.id):
        logger.info(f"⛔ Доступ к /{MODULE_NAME} запрещён для {message.from_user.id}")
        await message.answer(get_text("no_access"))
        return
    
    logger.info(f"📌 Запуск команды /{MODULE_NAME} для {message.from_user.id}")
    await update_stats("command_used")
    
    # Проверяем настройки
    settings = get_module_settings()
    if not settings["api_key"]:
        await message.answer(
            f"{MODULE_ICON} <b>API ключ не настроен!</b>\n"
            f"Для работы модуля необходимо указать API ключ OpenWeatherMap.\n"
            f"Получите бесплатный ключ на https://openweathermap.org и настройте его.",
            reply_markup=get_settings_kb(),
            parse_mode="HTML"
        )
        await state.set_state(WeatherStates.settings)
        return
    
    # Отправляем приветственное сообщение
    await message.answer(
        f"{MODULE_ICON} {get_text('welcome')}\n"
        f"Выберите действие или введите название города для получения прогноза:",
        reply_markup=get_main_menu_kb(),
        parse_mode="HTML"
    )
    
    await state.set_state(WeatherStates.main)

async def process_weather_message(message: types.Message, state: FSMContext) -> None:
    """Обрабатывает сообщение с названием города"""
    user_id = message.from_user.id
    city = message.text.strip()
    
    # Отправляем сообщение о загрузке
    loading_message = await message.answer(get_text("loading", city=city))
    
    # Получаем погоду
    weather_data = await get_current_weather(city)
    
    if "error" in weather_data:
        await loading_message.edit_text(get_text("not_found", city=city))
        return
    
    # Проверяем, добавлен ли город в избранное
    favorite_cities = await get_favorite_cities(user_id)
    is_favorite = city in favorite_cities
    
    # Форматируем сообщение о погоде
    weather_message = format_weather_message(weather_data, "current")
    
    # Отправляем сообщение с погодой
    await loading_message.edit_text(
        weather_message,
        reply_markup=get_forecast_kb(city, is_favorite),
        parse_mode="HTML"
    )

# --- Обработчики колбэков ---
async def process_callback(callback: types.CallbackQuery, state: FSMContext, kernel_data: Dict[str, Any]) -> None:
    """Обрабатывает нажатия на inline-кнопки"""
    if not is_module_enabled():
        logger.info(f"⛔ Модуль {DISPLAY_NAME} ({MODULE_NAME}) отключён")
        await callback.answer(get_text("disabled"), show_alert=True)
        return
    
    if not check_permissions(callback.from_user.id):
        logger.info(f"⛔ Доступ к колбэку {callback.data} запрещён для {callback.from_user.id}")
        await callback.answer(get_text("no_access"), show_alert=True)
        return
    
    user_id = callback.from_user.id
    data = callback.data
    logger.info(f"🔍 Обработка колбэка: {data} от {user_id}")
    await update_stats(f"callback_{data.split(':')[0]}")
    
    if data == "search_city":
        await callback.message.edit_text(
            get_text("city_prompt"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
            ])
        )
        await state.set_state(WeatherStates.city_input)
    
    elif data == "favorites":
        favorite_cities = await get_favorite_cities(user_id)
        
        if not favorite_cities:
            await callback.message.edit_text(
                get_text("favorites_empty"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
                ])
            )
        else:
            await callback.message.edit_text(
                get_text("favorites_title"),
                reply_markup=get_favorites_kb(favorite_cities),
                parse_mode="HTML"
            )
        
        await state.set_state(WeatherStates.favorites)
    
    elif data == "detailed_forecast":
        default_city = await get_user_city(user_id)
        await callback.answer(f"Загружаю прогноз для {default_city}...")
        
        weather_data = await get_current_weather(default_city)
        forecast_message = format_weather_message(weather_data, "forecast")
        
        await callback.message.edit_text(
            forecast_message,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
            ]),
            parse_mode="HTML"
        )
    
    elif data == "settings":
        await callback.message.edit_text(
            get_text("settings_title"),
            reply_markup=get_settings_kb(),
            parse_mode="HTML"
        )
        await state.set_state(WeatherStates.settings)
    
    elif data == "main_menu":
        await callback.message.edit_text(
            f"{MODULE_ICON} {get_text('welcome')}\n"
            f"Выберите действие или введите название города для получения прогноза:",
            reply_markup=get_main_menu_kb(),
            parse_mode="HTML"
        )
        await state.set_state(WeatherStates.main)
    
    elif data.startswith("get_weather:"):
        city = data.split(":", 1)[1]
        await callback.answer(f"Загружаю погоду для {city}...")
        
        weather_data = await get_current_weather(city)
        favorite_cities = await get_favorite_cities(user_id)
        is_favorite = city in favorite_cities
        
        weather_message = format_weather_message(weather_data, "current")
        
        await callback.message.edit_text(
            weather_message,
            reply_markup=get_forecast_kb(city, is_favorite),
            parse_mode="HTML"
        )
    
    elif data.startswith("add_favorite:"):
        city = data.split(":", 1)[1]
        await add_favorite_city(user_id, city)
        await callback.answer(get_text("city_added", city=city))
        
        # Обновляем сообщение с новыми кнопками
        await callback.message.edit_reply_markup(
            reply_markup=get_forecast_kb(city, True)
        )
    
    elif data.startswith("remove_favorite:"):
        city = data.split(":", 1)[1]
        await remove_favorite_city(user_id, city)
        await callback.answer(get_text("city_removed", city=city))
        
        # Обновляем сообщение с новыми кнопками
        await callback.message.edit_reply_markup(
            reply_markup=get_forecast_kb(city, False)
        )
    
    elif data.startswith("set_default:"):
        city = data.split(":", 1)[1]
        await set_user_city(user_id, city)
        await callback.answer(get_text("city_default", city=city))
    
    elif data.startswith("forecast:"):
        city = data.split(":", 1)[1]
        await callback.answer(f"Загружаю прогноз на 5 дней...")
        
        weather_data = await get_current_weather(city)
        forecast_message = format_weather_message(weather_data, "forecast")
        
        await callback.message.edit_text(
            forecast_message,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"get_weather:{city}")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
            ]),
            parse_mode="HTML"
        )
    
    elif data.startswith("temp_chart:"):
        city = data.split(":", 1)[1]
        await callback.answer("Создаю график температур...")
        
        chart_path = await generate_temperature_chart(city)
        
        if chart_path:
            with open(chart_path, 'rb') as chart:
                await callback.message.answer_photo(
                    photo=types.BufferedInputFile(chart.read(), filename="temperature_chart.png"),
                    caption=f"📊 График температур для {city} на неделю",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"get_weather:{city}")],
                        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
                    ])
                )
        else:
            await callback.message.answer(
                "❌ Не удалось создать график. Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
                ])
            )
    
    elif data.startswith("edit_setting:"):
        setting_key = data.split(":", 1)[1]
        settings = get_module_settings()
        current_value = settings.get(setting_key, "Не задано")
        
        setting_info = DEFAULT_SETTINGS.get(setting_key, {})
        setting_description = setting_info.get("description", "") if isinstance(setting_info, dict) else ""
        
        await callback.message.edit_text(
            f"⚙️ <b>Редактирование настройки</b>\n"
            f"═══════════════════════\n"
            f"🔧 <b>Настройка:</b> {setting_key}\n"
            f"📝 <b>Описание:</b> {setting_description}\n"
            f"🔵 <b>Текущее значение:</b> {current_value}\n\n"
            f"Введите новое значение или нажмите 'Отмена':",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="settings")]
            ]),
            parse_mode="HTML"
        )
        
        await state.update_data(editing_setting=setting_key)
        await state.set_state(WeatherStates.edit_setting)
    
    # Завершаем обработку колбэка
    if not data.startswith("get_weather:") and not data.startswith("temp_chart:"):
        await callback.answer()

# --- Фоновая задача для уведомлений ---
async def weather_notification_task() -> None:
    """Фоновая задача для отправки уведомлений о погоде"""
    while True:
        try:
            settings = get_module_settings()
            if settings["notifications_enabled"]:
                # Время уведомления
                notification_time = settings["notification_time"]
                hour, minute = map(int, notification_time.split(":"))
                
                # Текущее время
                now = datetime.now()
                
                # Проверяем, пора ли отправлять уведомление
                if now.hour == hour and now.minute == minute:
                    # Загружаем данные о пользователях
                    config = load_local_config()
                    user_preferences = config.get("user_preferences", {})
                    
                    # Для каждого пользователя
                    for user_id_str, prefs in user_preferences.items():
                        try:
                            user_id = int(user_id_str)
                            city = prefs.get("default_city", "Москва")
                            
                            # Получаем погоду
                            weather_data = await get_current_weather(city)
                            
                            if "error" not in weather_data:
                                # Формируем сообщение
                                weather_message = format_weather_message(weather_data, "current")
                                
                                # Отправляем уведомление
                                await kernel_data["bot"].send_message(
                                    user_id,
                                    f"{MODULE_ICON} <b>Ежедневный прогноз погоды</b>\n\n{weather_message}",
                                    reply_markup=get_forecast_kb(city),
                                    parse_mode="HTML"
                                )
                                logger.info(f"📧 Отправлено уведомление о погоде для {user_id}")
                        except Exception as e:
                            logger.error(f"❌ Ошибка отправки уведомления пользователю {user_id_str}: {e}")
                    
                    # Ждем минуту, чтобы не отправлять уведомления повторно
                    await asyncio.sleep(60)
                else:
                    # Ждем минуту до следующей проверки
                    await asyncio.sleep(60)
            else:
                # Если уведомления отключены, проверяем раз в час
                await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"❌ Ошибка в фоновой задаче уведомлений: {e}")
            await asyncio.sleep(300)  # В случае ошибки ждем 5 минут

# --- Регистрация модуля ---
def register_module(dp: Dispatcher, data: Dict[str, Any]) -> None:
    """Регистрирует модуль в системе бота"""
    global kernel_data
    kernel_data = data
    
    # Регистрация команды
    dp.message.register(weather_command, Command(commands=[MODULE_NAME]))
    
    # Регистрация обработчика сообщений с названиями городов
    from aiogram.filters import StateFilter
    dp.message.register(
        process_weather_message,
        StateFilter(WeatherStates.city_input) | StateFilter(WeatherStates.main)
    )
    
    # Регистрация обработчика колбэков
    from aiogram.filters import Text
    module_callbacks = [
        "search_city", "favorites", "detailed_forecast", "settings", "main_menu"
    ]
    dp.callback_query.register(
        process_callback,
        Text(startswith=tuple(module_callbacks)) | 
        Text(startswith=("get_weather:", "add_favorite:", "remove_favorite:", 
                         "set_default:", "forecast:", "temp_chart:", "edit_setting:"))
    )
    
    # Регистрация команды в меню бота
    command_registry = kernel_data["command_registry"]
    command_registry.register_command(
        command=MODULE_NAME,
        description=f"Прогноз погоды",
        icon=MODULE_ICON,
        category="Utility",
        admin=False
    )
    logger.info(f"✅ Модуль {DISPLAY_NAME} ({MODULE_NAME}) зарегистрирован")

# --- Установка модуля ---
async def install(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Выполняется при установке модуля"""
    global kernel_data, MODULE_DATA_DIR, PLOTS_DIR
    kernel_data = data
    
    # Создаем директории для данных модуля
    MODULE_DATA_DIR = os.path.join(data["base_dir"], "data", MODULE_NAME)
    PLOTS_DIR = os.path.join(MODULE_DATA_DIR, "plots")
    
    os.makedirs(MODULE_DATA_DIR, exist_ok=True)
    os.makedirs(PLOTS_DIR, exist_ok=True)
    
    # Инициализируем локальный конфиг
    config_path = get_local_config_path()
    if not os.path.exists(config_path):
        default_local_config = {
            "version": VERSION,
            "last_update": str(datetime.now()),
            "user_preferences": {}
        }
        save_local_config(default_local_config)
    
    logger.info(f"✅ Модуль {DISPLAY_NAME} ({MODULE_NAME}) установлен")
    
    # Возвращаем настройки модуля
    return DEFAULT_SETTINGS

# --- Завершение работы ---
async def on_shutdown(data: Dict[str, Any]) -> None:
    """Выполняется при выключении бота"""
    logger.info(f"🛑 Модуль {DISPLAY_NAME} ({MODULE_NAME}) завершает работу")
    CACHE.clear()

# --- Регистрация фоновых задач ---
def register_background_tasks(data: Dict[str, Any]) -> None:
    """Регистрирует фоновые задачи в ядре"""
    data["background_tasks"][MODULE_NAME] = [weather_notification_task]
    logger.info(f"🕒 Фоновая задача для {DISPLAY_NAME} зарегистрирована")