from aiogram import Router, Bot
from aiogram.types import Message
from aiogram.filters import Command
from core.decorators import user_command

router = Router()

def setup(kernel_data: dict):
    router.message.register(news_handler, Command("news"))
    kernel_data["dp"].include_router(router)

@user_command
async def news_handler(message: Message):
    await message.answer("📰 Новости: Пока нет новостей, настройте в /sysconf!")

def get_commands() -> list:
    return [
        {"command": "news", "description": "Последние новости", "admin": False, "icon": "📰"}
    ]