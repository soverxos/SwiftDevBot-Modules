from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command
from core.decorators import user_command

router = Router()

def setup(kernel_data: dict):
    router.message.register(weather_handler, Command("weather"))
    kernel_data["dp"].include_router(router)

@user_command
async def weather_handler(message: Message):
    await message.answer("🌦 Погода: Пока не настроена, укажите город через /sysconf!")

def get_commands() -> list:
    return [
        {"command": "weather", "description": "Показать погоду", "admin": False, "icon": "🌦"}
    ]
