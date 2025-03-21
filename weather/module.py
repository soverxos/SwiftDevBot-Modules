import os
import json
import logging
import aiosqlite
import asyncio
import requests
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

logger = logging.getLogger(__name__)

router = Router()

_kernel_data = None

class WeatherStates(StatesGroup):
    waiting_for_city = State()

DESCRIPTION = "Модуль для получения погоды в указанном городе."
GLOBAL_PARAMETERS = {
    "api_key": {
        "description": "API ключ для OpenWeatherMap",
        "required": True
    }
}
USER_PARAMETERS = {
    "city": {
        "description": "Город для получения погоды",
        "required": False
    }
}

def setup(kernel_data):
    global _kernel_data
    _kernel_data = kernel_data
    db = kernel_data["db"]
    asyncio.create_task(init_db(db))
    init_config(kernel_data["base_dir"])
    kernel_data["logger"].info("Модуль weather_module загружен и настроен")

async def init_db(db):
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='weather_config'") as cursor:
        if not await cursor.fetchone():
            await db.execute("""
                CREATE TABLE weather_config (
                    user_id INTEGER PRIMARY KEY,
                    city TEXT
                )
            """)
            await db.commit()
    logger.info("Таблица weather_config инициализирована")

def init_config(base_dir):
    config_path = os.path.join(base_dir, "modules", "weather_module", "config.json")
    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)
    logger.info(f"Конфигурация weather_module инициализирована: {config_path}")

def load_config(base_dir):
    config_path = os.path.join(base_dir, "modules", "weather_module", "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

async def get_user_config(db, user_id):
    async with db.execute("SELECT city FROM weather_config WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
        if row:
            return {"city": row[0]}
    return {}

async def set_user_config(db, user_id, config):
    if config is None:
        await db.execute("DELETE FROM weather_config WHERE user_id = ?", (user_id,))
    else:
        city = config.get("city")
        await db.execute("INSERT OR REPLACE INTO weather_config (user_id, city) VALUES (?, ?)", (user_id, city))
    await db.commit()

async def get_weather(city, api_key):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric&lang=ru"
    try:
        response = requests.get(url)
        if response.status_code != 200:
            return f"Ошибка: не удалось получить данные о погоде для {city} (код {response.status_code})"
        data = response.json()
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        description = data["weather"][0]["description"]
        return f"Погода в {city}:\nТемпература: {temp}°C\nОщущается как: {feels_like}°C\nОписание: {description}"
    except Exception as e:
        return f"Ошибка при получении погоды для {city}: {e}"

@router.message(Command("weather"))
async def weather_command(message: types.Message, state: FSMContext):
    if _kernel_data is None:
        await message.answer("Ошибка: модуль не инициализирован корректно!")
        return
    
    db = _kernel_data["db"]
    user_config = await get_user_config(db, message.from_user.id)
    city = user_config.get("city")
    
    if not city:
        await message.answer("Пожалуйста, укажите город для получения погоды:")
        await state.set_state(WeatherStates.waiting_for_city)
        return
    
    config = load_config(_kernel_data["base_dir"])
    api_key = config.get("api_key")
    if not api_key:
        await message.answer("Ошибка: API ключ не настроен. Обратитесь к администратору.")
        return
    
    weather_info = await get_weather(city, api_key)
    await message.answer(weather_info)

@router.message(WeatherStates.waiting_for_city)
async def process_city_input(message: types.Message, state: FSMContext):
    if _kernel_data is None:
        await message.answer("Ошибка: модуль не инициализирован корректно!")
        return
    
    city = message.text.strip()
    db = _kernel_data["db"]
    await set_user_config(db, message.from_user.id, {"city": city})
    await state.clear()
    
    config = load_config(_kernel_data["base_dir"])
    api_key = config.get("api_key")
    if not api_key:
        await message.answer("Ошибка: API ключ не настроен. Обратитесь к администратору.")
        return
    
    weather_info = await get_weather(city, api_key)
    await message.answer(weather_info)

def get_commands():
    return [
        {"command": types.BotCommand(command="/weather", description="Узнать погоду в городе"), "access": "all"}
    ]

async def on_startup(data):
    logger.info("Модуль weather_module запущен")

async def on_shutdown(data):
    logger.info("Модуль weather_module завершён")
