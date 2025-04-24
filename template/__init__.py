"""
Полный шаблон модуля для SwiftDevBot.

Этот файл является точкой входа для модуля и отвечает только за регистрацию
компонентов модуля в системе. Основная логика вынесена в отдельные файлы.
"""
from aiogram import Bot, Dispatcher, Router

from app.utils import get_module_logger
from . import handlers
from . import utils

# Создаем логгер для модуля
logger = get_module_logger("template_full")


async def setup(bot: Bot, dp: Dispatcher, router: Router):
    """
    Настраивает модуль при загрузке.
    
    Аргументы:
        bot: Объект бота
        dp: Диспетчер
        router: Роутер для регистрации обработчиков
    """
    # Инициализируем общие данные модуля (если необходимо)
    await utils.init_module_data()
    
    # Регистрируем обработчики
    handlers.register_handlers(router)
    
    logger.info("Модуль template_full успешно загружен")


async def cleanup():
    """
    Выполняет очистку при выгрузке модуля.
    """
    # Сохраняем данные модуля (если необходимо)
    await utils.save_module_data()
    
    logger.info("Модуль template_full выгружается")
