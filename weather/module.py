import json
import logging
import os
import requests
from aiogram import types
from aiogram.filters import Command
from core.modules import get_loaded_modules

logger = logging.getLogger("weather_module")

# Путь к файлу api.json
API_JSON_PATH = os.path.join(os.path.dirname(__file__), "api.json")

# Загрузка API ключа из api.json
def load_api_key():
    try:
        with open(API_JSON_PATH, "r", encoding="utf-8") as f:
            api_data = json.load(f)
            return api_data.get("WEATHER_API_KEY")
    except Exception as e:
        logger.error(f"Ошибка загрузки API ключа из api.json: {e}")
        return None

WEATHER_API_KEY = load_api_key()
if not WEATHER_API_KEY:
    logger.error("WEATHER_API_KEY не найден в api.json!")
    raise ValueError("WEATHER_API_KEY не найден в api.json!")

# Базовый URL для API OpenWeatherMap
WEATHER_API_URL = "https://api.openweathermap.org/data/2.5/weather"

def setup(kernel_data):
    dp = kernel_data["dp"]
    dp.message.register(weather_command, Command("weather"))
    logger.info("Модуль погоды загружен и настроен.")

async def weather_command(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Пожалуйста, укажите город: /weather <город>")
        return

    city = args[1]
    try:
        weather_data = await get_weather(city)
        if weather_data:
            response = format_weather_response(weather_data)
            await message.answer(response)
        else:
            await message.answer("Не удалось получить данные о погоде.")
    except Exception as e:
        logger.error(f"Ошибка при получении погоды: {e}")
        await message.answer("Произошла ошибка при получении данных о погоде.")

async def get_weather(city: str):
    params = {
        "q": city,
        "appid": WEATHER_API_KEY,
        "units": "metric",  # Используем метрическую систему
        "lang": "ru"        # Язык ответа - русский
    }
    try:
        logger.info(f"Отправка запроса к API: {params}")
        response = requests.get(WEATHER_API_URL, params=params)
        response.raise_for_status()  # Проверяем, что ответ успешный
        logger.info(f"Ответ от API: {response.json()}")
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Ошибка запроса к API погоды: {e}")
        logger.error(f"Ответ от сервера: {e.response.text if e.response else 'Нет ответа'}")
        return None

def format_weather_response(weather_data):
    city = weather_data.get("name", "Неизвестный город")
    temp = round(weather_data["main"].get("temp", 0))  # Округляем до целого числа
    feels_like = round(weather_data["main"].get("feels_like", 0))  # Округляем до целого числа
    humidity = weather_data["main"].get("humidity", "N/A")
    wind_speed = weather_data["wind"].get("speed", "N/A")
    weather_description = weather_data["weather"][0].get("description", "N/A")

    response = (
        f"🌍 Город: {city}\n"
        f"🌡 Температура: {temp}°C\n"
        f"🤔 Ощущается как: {feels_like}°C\n"
        f"💧 Влажность: {humidity}%\n"
        f"🌬 Скорость ветра: {wind_speed} м/с\n"
        f"☁️ Погода: {weather_description.capitalize()}"
    )
    return response

def get_commands():
    return [types.BotCommand(command="/weather", description="🌤 Узнать погоду в городе")]